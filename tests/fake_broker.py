#!/usr/bin/env python3
"""Minimaler MQTT-3.1.1-Testbroker: protokolliert alle PUBLISH als JSON-Zeilen.

Beantwortet CONNECT, SUBSCRIBE und PINGREQ. Mit drittem Argument "online" sendet er kurz nach dem
SUBSCRIBE "online" auf homeassistant/status (simuliert einen Home-Assistant-Neustart).

  python3 tests/fake_broker.py 18830 broker.log [online]

Testlauf des Add-ons mit Mitschnitten (.cu8 von tools/… bzw. rtl_433 -S all), z. B. im Container:
  docker build -t eimsig-test --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20 eimsig2mqtt/
  docker run --rm --network host -v $PWD/options.json:/opts/options.json:ro -v $PWD/data:/data \
    -v /pfad/zu/mitschnitten:/m:ro -e MQTT_HOST=127.0.0.1 -e MQTT_PORT=18830 \
    -e EIMSIG_OPTIONS=/opts/options.json -e EIMSIG_DATA=/data -e EIMSIG_REPLAY=/m/g001.cu8:/m/g002.cu8 \
    --entrypoint python3 eimsig-test -u /app/eimsig2mqtt.py
Liegt neben den .cu8-Dateien eine bursts.csv (Spalten datei, zeit), werden deren Zeitstempel verwendet.
"""
import json
import socket
import struct
import sys
import threading
import time


def rx(c, n):
    b = bytearray()
    while len(b) < n:
        d = c.recv(n - len(b))
        if not d:
            raise ConnectionError("Verbindung geschlossen")
        b += d
    return bytes(b)


def read_packet(c):
    h = rx(c, 1)[0]
    mult, n = 1, 0
    while True:
        b = rx(c, 1)[0]
        n += (b & 0x7F) * mult
        if not b & 0x80:
            break
        mult *= 128
    return h, rx(c, n) if n else b""


def s16(b):
    return struct.pack(">H", len(b)) + b


def publish(topic, payload):
    body = s16(topic.encode()) + payload.encode()
    return bytes([0x30, len(body)]) + body


def main():
    port, out = int(sys.argv[1]), open(sys.argv[2], "w", encoding="utf-8")
    online = len(sys.argv) > 3 and sys.argv[3] == "online"
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)

    def w(d):
        out.write(json.dumps(d, ensure_ascii=False) + "\n")
        out.flush()

    def client(c):
        gesendet = False
        try:
            while True:
                typ, body = read_packet(c)
                art = typ & 0xF0
                if art == 0x10:  # CONNECT
                    pl = struct.unpack(">H", body[:2])[0]
                    flags, pos = body[2 + pl + 1], 2 + pl + 4

                    def feld(p):
                        ln = struct.unpack(">H", body[p:p + 2])[0]
                        return body[p + 2:p + 2 + ln].decode(), p + 2 + ln
                    cid, pos = feld(pos)
                    will = None
                    if flags & 0x04:
                        wt, pos = feld(pos)
                        wm, pos = feld(pos)
                        will = [wt, wm, bool(flags & 0x20)]
                    user = feld(pos)[0] if flags & 0x80 else None
                    w({"connect": cid, "will": will, "user": user, "level": body[2 + pl]})
                    c.sendall(b"\x20\x02\x00\x00")
                elif art == 0x30:  # PUBLISH
                    tl = struct.unpack(">H", body[:2])[0]
                    off = 2 + tl + (2 if (typ >> 1) & 3 else 0)
                    w({"t": body[2:2 + tl].decode(), "p": body[off:].decode(), "r": bool(typ & 1)})
                elif art == 0x80:  # SUBSCRIBE
                    c.sendall(b"\x90\x03" + body[:2] + b"\x00")
                    if online and not gesendet:
                        gesendet = True
                        threading.Thread(target=lambda: (time.sleep(1.5),
                                         c.sendall(publish("homeassistant/status", "online"))), daemon=True).start()
                elif art == 0xC0:  # PINGREQ
                    c.sendall(b"\xd0\x00")
                elif art == 0xE0:  # DISCONNECT
                    w({"disconnect": True})
                    return
        except Exception as e:  # noqa: BLE001
            w({"ende": repr(e)})

    while True:
        c, _ = srv.accept()
        threading.Thread(target=client, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
