"""EiMSIG EM-Z100 Funkprotokoll (868,3 MHz) – Dekodierung aus RTL-SDR-Rohdaten über rtl_tcp.

Reines Python, keine Abhängigkeiten. Beschreibung des Protokolls: docs/PROTOKOLL.md

Funk: OOK, KeeLoq/HCS-artige PWM (TE ≈ 400 µs), 66 Bit, kurzer Puls = 1, langer Puls = 0.
Klartext-Telegramme (Bits 60–63 = 0000): Fenstersensoren und Zentrale-Status, 4-Bit-XOR-Prüfsumme in Bits 16–19.
Rollende Telegramme (Bits 60–63 ≠ 0000): Handsender und Scharf-Status der Zentrale; Bits 0–31 verschlüsselt,
Seriennummer (32–59) und Tasten (60–63) im Klartext.
"""
import datetime as dt
import socket
import struct
import time
from collections import deque

RATE = 1024000                          # Samplerate (S/s)
FREQ = 868.3e6
DEC = 4                                 # Dezimierung für die Pulsanalyse
SQ = [(i - 127.5) ** 2 for i in range(256)]

TYP = {0x27: "Fenstersensor", 0x2B: "Zentrale"}
OFFEN = 255                             # Code „offen“ bei allen Fenstersensoren
# Standardbedeutung der Sensorcodes, bis das Add-on sie von der Zentrale gelernt hat.
# Familie A: zu 38 / gekippt 165, Familie B: zu 166 / gekippt 101. 2-Stellungs-Sensoren
# senden geschlossen den Kipp-Code ihrer Familie (das regelt die Typ-Einstellung bzw. das Lernen).
STANDARD = {255: "OFFEN", 165: "GEKIPPT", 101: "GEKIPPT", 38: "ZU", 166: "ZU"}
ZENTRALE_STATUS = {38: "grün", 165: "gelb", 255: "rot"}       # Byte 0 im Klartext-Telegramm der Zentrale
ZENTRALE_SCHARF = {"1011": "scharf", "1001": "unscharf"}       # Tasten im rollenden Telegramm der Zentrale
HANDSENDER_TASTEN = {"0100": "scharf", "1000": "unscharf"}     # rote / grüne Taste
SERIEN_MASKE = (1 << 27) - 1            # Bit 59 unterscheidet Klartext- und rollende Nummer der Zentrale


def gleiche_zentrale(sn_rollend, sn_klartext):
    """Rollende Nummer der Zentrale = Klartext-Nummer mit gesetztem Bit 59 (beobachtet)."""
    return sn_klartext is not None and (sn_rollend & SERIEN_MASKE) == (sn_klartext & SERIEN_MASKE)


# ---------- Dekodierung ----------
def pulse_runs(data):
    """IQ-Bytes (unsigned 8 bit) -> Liste (an?, dauer_us) auf Basis der Hüllkurve."""
    sl = [data[k::2 * DEC] for k in range(2 * DEC)]
    m = [sum(map(SQ.__getitem__, t)) for t in zip(*sl)]
    if len(m) < 100:
        return []
    s = sorted(m)
    lo, hi = s[len(s) // 10], s[-max(1, len(s) // 100)]
    if hi < lo * 4:
        return []
    thr = (lo + hi) / 2
    us = DEC * 1e6 / RATE
    runs, cur, n = [], m[0] > thr, 0
    for v in m:
        b = v > thr
        if b == cur:
            n += 1
        else:
            runs.append((cur, n * us))
            cur, n = b, 1
    runs.append((cur, n * us))
    return runs


def packets(runs, gap_us=2000):
    pk, cur = [], []
    for b, us in runs:
        if not b and us > gap_us:
            if cur:
                pk.append(cur)
                cur = []
        elif cur or b:
            cur.append((b, us))
    if cur:
        pk.append(cur)
    return pk


def valid_bits(pk):
    hi = [us for b, us in pk if b]
    lo = [us for b, us in pk if not b]
    if len(hi) != 66 or len(lo) < 65:
        return None
    for k, h in enumerate(hi):
        if not (250 <= h <= 550 or 650 <= h <= 1000):
            return None
        if k < 65 and not (950 <= h + lo[k] <= 1500):
            return None
    return "".join("1" if h < 600 else "0" for h in hi)


def checksum_ok(b):
    for t in range(16, 20):
        x = sum(int(b[i]) for i in range(66) if i % 4 == t % 4 and not 16 <= i < 20) % 2
        if x != int(b[t]):
            return False
    return True


def le(bits):
    return int(bits[::-1], 2)


def telegramm_aus_bits(b):
    klartext = b[60:64] == "0000"
    return dict(bits=b, serial=le(b[32:60]),
                typ=TYP.get(le(b[24:32]), f"0x{le(b[24:32]):02X}") if klartext else "rollend",
                klartext=klartext, ok=checksum_ok(b) if klartext else None,
                pos=int(b[0:8], 2), tasten=b[60:64], nachmeldung=b[8] == "1", status=b[64:66])


def telegramme(data):
    """Alle gültigen, verschiedenen Telegramme eines Bursts."""
    out, seen = [], set()
    for pk in packets(pulse_runs(data)):
        b = valid_bits(pk)
        if b and b not in seen:
            seen.add(b)
            out.append(telegramm_aus_bits(b))
    return out


# ---------- rtl_tcp ----------
def _recv_exact(s, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Verbindung von rtl_tcp geschlossen")
        buf += chunk
    return bytes(buf)


def empfangen(host, port, handler, on_status=None, gain=40.2, freq=FREQ, log=print):
    """Endlosschleife: rtl_tcp verbinden, Bursts erkennen, handler(telegramm, zeit, pegel_db) aufrufen.
    Verbindet bei Fehlern nach 5 s neu. on_status(True/False) meldet den Verbindungszustand."""
    import math
    blk = 8192 * 2
    pre_n, post_n, max_n = 6, 12, int(1.5 * RATE * 2 / blk)
    while True:
        try:
            s = socket.create_connection((host, port), timeout=10)
            hdr = _recv_exact(s, 12)
            if hdr[:4] != b"RTL0":
                raise ConnectionError(f"kein rtl_tcp: {hdr[:4]!r}")
            for cmd, val in ((0x02, RATE), (0x01, int(freq)), (0x03, 1), (0x04, int(gain * 10)), (0x08, 0)):
                s.sendall(struct.pack(">BI", cmd, val))
            log(f"rtl_tcp verbunden: {host}:{port}, {freq / 1e6:.1f} MHz, {gain} dB")
            if on_status:
                on_status(True)
            _recv_exact(s, blk * 40)
            hist, pre, cur, quiet, peak, t0 = deque(maxlen=250), deque(maxlen=pre_n), None, 0, 0.0, None
            while True:
                d = _recv_exact(s, blk)
                p = sum(map(SQ.__getitem__, d[::8])) / (blk // 8)
                floor = sorted(hist)[len(hist) // 3] if len(hist) > 20 else p
                active = len(hist) > 20 and p > floor * 4
                if cur is None:
                    if active:
                        cur, quiet, peak, t0 = bytearray(b"".join(pre)) + d, 0, p / floor, dt.datetime.now()
                    else:
                        hist.append(p)
                        pre.append(d)
                    continue
                cur += d
                peak = max(peak, p / floor)
                quiet = 0 if active else quiet + 1
                if quiet >= post_n or len(cur) >= max_n * blk:
                    for t in telegramme(bytes(cur)):
                        handler(t, t0, 10 * math.log10(peak))
                    cur, pre = None, deque(maxlen=pre_n)
        except Exception as e:  # noqa: BLE001 – jede Störung führt zur Neuverbindung
            if on_status:
                on_status(False)
            log(f"rtl_tcp: {e} – neuer Versuch in 5 s")
            time.sleep(5)
