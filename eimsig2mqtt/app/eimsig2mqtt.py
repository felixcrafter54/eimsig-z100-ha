#!/usr/bin/env python3
"""eimsig2mqtt – EiMSIG EM-Z100 über rtl_tcp mitlesen und per MQTT Discovery an Home Assistant melden.

Nur lesend: es wird nichts an die Alarmanlage gesendet.

Umgebungsvariablen (setzt run.sh im Add-on):
  MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASSWORD
  RTL_TCP_HOST, RTL_TCP_PORT      Quelle (bei USB startet run.sh einen lokalen rtl_tcp)
  EIMSIG_OPTIONS   Pfad zur options.json (Standard /data/options.json)
  EIMSIG_DATA      Ordner für erkannte Geräte, gelernte Codes und letzte Zustände (Standard /data)
  EIMSIG_REPLAY    Test: .cu8-Dateien (durch ":" getrennt) statt rtl_tcp abspielen
"""
import datetime as dt
import json
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eimsig_protokoll as ep  # noqa: E402
from mqtt_client import MQTT  # noqa: E402

VERSION = os.environ.get("EIMSIG_VERSION", "dev")
DATA = os.environ.get("EIMSIG_DATA", "/data")
P = "eimsig2mqtt"                     # Basis-Topic
D = "homeassistant"                   # Discovery-Präfix
AVAIL = f"{P}/status"
ZUST_HA = {"ZU": "zu", "GEKIPPT": "gekippt", "OFFEN": "offen"}
ANTWORT_S = 3                          # so schnell antwortet die Zentrale auf Sensor/Drücker (gemessen ~1 s)
BESTAETIGUNGEN = 2                     # so oft muss die Zentrale reagieren, bevor ein Gerät angelegt wird


def log(msg):
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


def jetzt():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def lade_json(pfad, standard):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return standard


def speichere_json(pfad, daten):
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=2, ensure_ascii=False)
    os.replace(tmp, pfad)


class Bridge:
    def __init__(self, opt, mqtt):
        self.opt, self.mqtt = opt, mqtt
        self.lock = threading.RLock()
        self.auto = bool(opt.get("geraete_automatisch_anlegen", True))
        # automatisch erkannte Geräte (überleben Neustarts)
        self.f_geraete = os.path.join(DATA, "geraete.json")
        g = lade_json(self.f_geraete, {})
        self.zentrale_sn = int(opt.get("zentrale_seriennr") or 0) or g.get("zentrale")
        self.auto_sensoren = {int(k): v for k, v in g.get("sensoren", {}).items()} if self.auto else {}
        self.auto_handsender = {int(k): v for k, v in g.get("handsender", {}).items()} if self.auto else {}
        # konfigurierte Geräte haben Vorrang (Name, Typ)
        self.sensoren = dict(self.auto_sensoren)
        self.sensoren.update({int(s["seriennr"]): {"name": s["name"], "typ": s.get("typ", "auto")}
                              for s in opt.get("sensoren", [])})
        self.handsender = dict(self.auto_handsender)
        self.handsender.update({int(h["seriennr"]): h["name"] for h in opt.get("handsender", [])})
        # gelernte Codes: sn -> {code: ZUSTAND}
        self.f_kal = os.path.join(DATA, "kalibrierung.json")
        self.kal = {int(sn): {int(c): z for c, z in codes.items()}
                    for sn, codes in lade_json(self.f_kal, {}).items()}
        # letzte Zustände
        self.f_zust = os.path.join(DATA, "zustand.json")
        gesp = lade_json(self.f_zust, {})
        self.fenster = {int(sn): v for sn, v in gesp.get("fenster", {}).items() if int(sn) in self.sensoren}
        self.zentrale = gesp.get("zentrale")
        self.alarm = gesp.get("alarm")
        self.funk = False
        self.letzte_sensor = None         # (sn, code, ts) – auch unbekannte, für Lernen und Erkennen
        self.letzter_hs = None            # (sn, tasten, ts) – unbekannter rollender Sender
        self.kandidaten = {}              # (sn, code, zustand) -> Anzahl (zum Überschreiben gelernter Codes)
        self.neu_kandidaten = {}          # ("s"|"h", sn) -> Anzahl Reaktionen der Zentrale
        self.tasten_zuletzt = {}
        self.unbekannt_gemeldet = set()
        self.f_angelegt = os.path.join(DATA, "angelegt.json")
        if self.zentrale_sn:
            log(f"Zentrale {self.zentrale_sn}" + (" (aus Konfiguration)" if opt.get("zentrale_seriennr") else ""))
        else:
            log("Zentrale noch unbekannt – wird am ersten Statustelegramm erkannt (spätestens nach ~30 s)")

    def _speichere_geraete(self):
        speichere_json(self.f_geraete, {"zentrale": self.zentrale_sn,
                                        "sensoren": {str(k): v for k, v in self.auto_sensoren.items()},
                                        "handsender": {str(k): v for k, v in self.auto_handsender.items()}})

    # ---------- Zustandslogik ----------
    def zustand(self, sn, code):
        if code in self.kal.get(sn, {}):
            return self.kal[sn][code]
        if code == ep.OFFEN:
            return "OFFEN"
        if self.sensoren.get(sn, {}).get("typ") in ("zwei_stellungen", "tuer"):
            return "ZU"
        return ep.STANDARD.get(code, "ZU")

    def lerne(self, sn, code, ziel):
        alt = self.kal.get(sn, {}).get(code)
        if alt == ziel:
            return
        name = self.sensoren[sn]["name"]
        if alt is not None:
            k = (sn, code, ziel)
            self.kandidaten[k] = self.kandidaten.get(k, 0) + 1
            if self.kandidaten[k] < 2:
                log(f"{name}: Zentrale deutet Code {code} als {ziel} (bisher {alt}) – warte auf Bestätigung")
                return
            self.kandidaten.pop(k, None)
        self.kal.setdefault(sn, {})[code] = ziel
        speichere_json(self.f_kal, {str(s): {str(c): z for c, z in cs.items()} for s, cs in self.kal.items()})
        log(f"{name}: Code {code} = {ziel} von der Zentrale gelernt" + (f" (vorher {alt})" if alt else ""))
        f = self.fenster.get(sn)
        if f and f.get("code") == code and f.get("zustand") != ziel:
            self._setze_fenster(sn, code, ziel, f.get("pegel"), "gelernt")

    def _speichere_zust(self):
        speichere_json(self.f_zust, {"fenster": {str(k): v for k, v in self.fenster.items()},
                                     "zentrale": self.zentrale, "alarm": self.alarm})

    # ---------- Telegramme ----------
    def handle(self, t, ts, pegel):
        with self.lock:
            try:
                self._handle(t, ts, round(pegel, 1))
            except Exception as e:  # noqa: BLE001 – ein kaputtes Telegramm darf den Dienst nicht beenden
                log(f"Fehler bei Telegramm {t.get('bits')}: {e!r}")

    def _handle(self, t, ts, pegel):
        sn = t["serial"]
        if not t["klartext"]:
            return self._rollend(sn, t["tasten"], ts, pegel)
        if not t["ok"]:
            return
        if t["typ"] == "Fenstersensor":
            self.letzte_sensor = (sn, t["pos"], ts, pegel)
            if sn in self.sensoren:
                code = t["pos"]
                self._setze_fenster(sn, code, self.zustand(sn, code), pegel, "funk")
            else:
                self._unbekannt(f"Fenstersensor {sn}", sn, code=t["pos"], pegel=pegel)
        elif t["typ"] == "Zentrale":
            if not self.zentrale_sn:
                self.zentrale_sn = sn
                self._speichere_geraete()
                log(f"Zentrale erkannt: {sn}")
            if sn != self.zentrale_sn:
                return self._unbekannt(f"andere Zentrale {sn}", sn)
            self._zentrale(t["pos"], ts, pegel)

    def _setze_fenster(self, sn, code, z, pegel, quelle, leise=False):
        alt = self.fenster.get(sn, {}).get("zustand")
        self.fenster[sn] = {"zustand": z, "code": code, "pegel": pegel, "zeit": jetzt(), "quelle": quelle}
        self._pub_fenster(sn)
        if alt != z:
            self._speichere_zust()
            if not leise:
                c = f"Code {code:3d}" if code is not None else "Code   –"
                p = f"{pegel} dB" if pegel is not None else ""
                log(f"{self.sensoren[sn]['name']:<18} {z:<8} {c}  {p}  ({quelle})")

    def _zentrale(self, code, ts, pegel):
        farbe = ep.ZENTRALE_STATUS.get(code)
        if farbe is None:
            return self._unbekannt(f"Zentrale-Status {code}", self.zentrale_sn)
        if (self.zentrale or {}).get("status") != farbe:
            log(f"Zentrale {farbe}")
        self.zentrale = {"status": farbe, "code": code, "pegel": pegel, "zeit": jetzt()}
        self._pub(f"{P}/zentrale/status", self.zentrale, retain=True)
        # Die Zentrale antwortet ~0,8 s nach einer Meldung IHRER Sensoren mit dem Gesamtstatus
        ls, self.letzte_sensor = self.letzte_sensor, None
        if ls and 0 <= (ts - ls[2]).total_seconds() <= ANTWORT_S:
            sn, scode, _, spegel = ls
            if sn not in self.sensoren:
                self._kandidat("s", sn)
            if sn in self.sensoren:
                andere_zu = all(self.fenster.get(o, {}).get("zustand") == "ZU" for o in self.sensoren if o != sn)
                if farbe == "grün":
                    self.lerne(sn, scode, "ZU")
                elif farbe == "gelb" and andere_zu:
                    self.lerne(sn, scode, "GEKIPPT")
                elif farbe == "rot" and scode == ep.OFFEN:
                    self.lerne(sn, scode, "OFFEN")
                if sn not in self.fenster or self.fenster[sn].get("code") == scode:
                    self._setze_fenster(sn, scode, self.zustand(sn, scode), spegel, "funk")
        # grün heißt: laut Zentrale ist alles zu (gleicht verpasste Meldungen aus)
        # – auch für Fenster, die seit dem Start noch nie gesendet haben (sonst „unbekannt“ bis zur ersten Meldung)
        if farbe == "grün":
            neu = []
            for sn in self.sensoren:
                f = self.fenster.get(sn)
                if f is None:
                    neu.append(self.sensoren[sn]["name"])
                    self._setze_fenster(sn, None, "ZU", None, "zentrale", leise=True)
                elif f.get("zustand") != "ZU":
                    log(f"{self.sensoren[sn]['name']}: laut Zentrale zu (war {f.get('zustand')}, Meldung verpasst?)")
                    self._setze_fenster(sn, f.get("code"), "ZU", f.get("pegel"), "zentrale")
            if neu:
                log(f"Zentrale grün → {len(neu)} Fenster/Türen ohne bisherige Meldung auf „zu“ gesetzt")
        self._speichere_zust()

    def _kandidat(self, art, sn):
        """Zentrale hat auf ein unbekanntes Gerät reagiert – nach BESTAETIGUNGEN Mal anlegen."""
        if not self.auto:
            return
        k = (art, sn)
        self.neu_kandidaten[k] = self.neu_kandidaten.get(k, 0) + 1
        if self.neu_kandidaten[k] < BESTAETIGUNGEN:
            log(f"{'Fenstersensor' if art == 's' else 'Handsender'} {sn}: Zentrale hat reagiert "
                f"({self.neu_kandidaten[k]}/{BESTAETIGUNGEN})")
            return
        self.neu_kandidaten.pop(k, None)
        if art == "s":
            self.auto_sensoren[sn] = self.sensoren[sn] = {"name": f"Fenster {sn}", "typ": "auto"}
            self._discovery_fenster(sn)
        else:
            self.auto_handsender[sn] = self.handsender[sn] = f"Handsender {sn}"
            self._discovery_handsender(sn)
        self._speichere_geraete()
        self._merke_angelegt()
        log(f"Neues Gerät angelegt: {'Fenster' if art == 's' else 'Handsender'} {sn} – in Home Assistant umbenennen")

    def _rollend(self, sn, tasten, ts, pegel):
        if ep.gleiche_zentrale(sn, self.zentrale_sn):
            z = ep.ZENTRALE_SCHARF.get(tasten, "unbekannt")
            if (self.alarm or {}).get("zustand") != z:
                log(f"Alarmanlage {z.upper()}" + (f" (Tasten {tasten} – evtl. Alarm?)" if z == "unbekannt" else ""))
                self.alarm = {"zustand": z, "tasten": tasten, "zeit": jetzt()}
                self._speichere_zust()
            self._pub(f"{P}/zentrale/alarm", self.alarm, retain=True)
            # Antwort auf einen unbekannten Drücker, dessen Taste zum neuen Zustand passt?
            lh, self.letzter_hs = self.letzter_hs, None
            if lh and 0 <= (ts - lh[2]).total_seconds() <= ANTWORT_S and ep.HANDSENDER_TASTEN.get(lh[1]) == z:
                self._kandidat("h", lh[0])
        elif sn in self.handsender:
            vor = self.tasten_zuletzt.get(sn)
            self.tasten_zuletzt[sn] = (tasten, ts)
            if vor and vor[0] == tasten and (ts - vor[1]).total_seconds() < 2:
                return
            ev = ep.HANDSENDER_TASTEN.get(tasten, "andere")
            log(f"{self.handsender[sn]}: Taste {ev} ({tasten})")
            self._pub(f"{P}/handsender/{sn}", {"event_type": ev, "tasten": tasten, "pegel": pegel})
        else:
            if not self.letzter_hs or self.letzter_hs[0] != sn or (ts - self.letzter_hs[2]).total_seconds() > 2:
                self.letzter_hs = (sn, tasten, ts)
            self._unbekannt(f"Funksender (rollend) {sn}", sn, tasten=tasten, pegel=pegel)

    def _unbekannt(self, text, sn, **extra):
        if sn not in self.unbekannt_gemeldet:
            self.unbekannt_gemeldet.add(sn)
            log(f"Unbekanntes Gerät: {text}  {extra or ''}")
        self._pub(f"{P}/unbekannt", dict(geraet=text, seriennr=sn, zeit=jetzt(), **extra), retain=True)

    def funk_status(self, ok):
        if ok != self.funk:
            self.funk = ok
            log("Funkempfang " + ("verbunden" if ok else "getrennt"))
        self.mqtt.publish(f"{P}/funk", "ON" if ok else "OFF", retain=True)

    # ---------- MQTT / Discovery ----------
    def _pub(self, topic, data, retain=False):
        self.mqtt.publish(topic, json.dumps(data, ensure_ascii=False), retain)

    def _pub_fenster(self, sn):
        f = dict(self.fenster[sn])
        f["zustand"] = ZUST_HA[f["zustand"]]
        self._pub(f"{P}/fenster/{sn}", f, retain=True)

    def _cfg(self, komp, objekt, eintrag, cfg):
        cfg.setdefault("availability_topic", AVAIL)
        cfg["unique_id"] = f"{objekt}_{eintrag}"
        topic = f"{D}/{komp}/{objekt}/{eintrag}/config"
        self.mqtt.publish(topic, json.dumps(cfg, ensure_ascii=False), retain=True)
        return topic

    def _zentrale_dev(self):
        d = {"identifiers": ["eimsig_zentrale"], "name": "EiMSIG Zentrale", "manufacturer": "EiMSIG",
             "model": "EM-Z100", "sw_version": f"eimsig2mqtt {VERSION}"}
        if self.zentrale_sn:
            d["serial_number"] = str(self.zentrale_sn)
        return d

    def _discovery_zentrale(self):
        dev = self._zentrale_dev()
        return [
            self._cfg("sensor", "eimsig_zentrale", "status", {
                "name": "Status", "device": dev, "state_topic": f"{P}/zentrale/status",
                "value_template": "{{ value_json.status }}", "json_attributes_topic": f"{P}/zentrale/status",
                "device_class": "enum", "options": ["grün", "gelb", "rot"], "icon": "mdi:traffic-light"}),
            self._cfg("sensor", "eimsig_zentrale", "alarmanlage", {
                "name": "Alarmanlage", "device": dev, "state_topic": f"{P}/zentrale/alarm",
                "value_template": "{{ value_json.zustand }}", "json_attributes_topic": f"{P}/zentrale/alarm",
                "device_class": "enum", "options": ["scharf", "unscharf", "unbekannt"], "icon": "mdi:shield-home"}),
            self._cfg("binary_sensor", "eimsig_zentrale", "scharf", {
                "name": "Scharf", "device": dev, "state_topic": f"{P}/zentrale/alarm",
                "value_template": "{{ 'ON' if value_json.zustand == 'scharf' else 'OFF' }}",
                "icon": "mdi:shield-lock"}),
            self._cfg("binary_sensor", "eimsig_zentrale", "funk", {
                "name": "Funkempfang", "device": dev, "state_topic": f"{P}/funk",
                "device_class": "connectivity", "entity_category": "diagnostic"}),
            self._cfg("sensor", "eimsig_zentrale", "unbekannt", {
                "name": "Unbekanntes Gerät", "device": dev, "state_topic": f"{P}/unbekannt",
                "value_template": "{{ value_json.geraet }}", "json_attributes_topic": f"{P}/unbekannt",
                "entity_category": "diagnostic", "icon": "mdi:radio-tower"}),
        ]

    def _discovery_fenster(self, sn):
        s = self.sensoren[sn]
        dev = {"identifiers": [f"eimsig_{sn}"], "name": s["name"], "manufacturer": "EiMSIG",
               "model": "Türsensor" if s.get("typ") == "tuer" else "Fenstersensor", "serial_number": str(sn),
               "via_device": "eimsig_zentrale"}
        st = f"{P}/fenster/{sn}"
        return [
            self._cfg("binary_sensor", f"eimsig_{sn}", "offen", {
                "name": None, "device": dev, "state_topic": st,
                "device_class": "door" if s.get("typ") == "tuer" else "window",
                "value_template": "{{ 'OFF' if value_json.zustand == 'zu' else 'ON' }}",
                "json_attributes_topic": st}),
            self._cfg("sensor", f"eimsig_{sn}", "zustand", {
                "name": "Zustand", "device": dev, "state_topic": st, "value_template": "{{ value_json.zustand }}",
                "device_class": "enum", "options": ["zu", "gekippt", "offen"], "icon": "mdi:window-closed-variant"}),
        ]

    def _discovery_handsender(self, sn):
        dev = {"identifiers": [f"eimsig_hs_{sn}"], "name": self.handsender[sn], "manufacturer": "EiMSIG",
               "model": "Handsender", "serial_number": str(sn), "via_device": "eimsig_zentrale"}
        return [self._cfg("event", f"eimsig_hs_{sn}", "taste", {
            "name": "Taste", "device": dev, "state_topic": f"{P}/handsender/{sn}",
            "event_types": ["scharf", "unscharf", "andere"], "device_class": "button", "icon": "mdi:remote"})]

    def _alle_topics(self):
        return ([f"{D}/{k}/eimsig_zentrale/{e}/config" for k, e in
                 (("sensor", "status"), ("sensor", "alarmanlage"), ("binary_sensor", "scharf"),
                  ("binary_sensor", "funk"), ("sensor", "unbekannt"))]
                + [f"{D}/{k}/eimsig_{sn}/{e}/config" for sn in self.sensoren
                   for k, e in (("binary_sensor", "offen"), ("sensor", "zustand"))]
                + [f"{D}/event/eimsig_hs_{sn}/taste/config" for sn in self.handsender])

    def _merke_angelegt(self):
        speichere_json(self.f_angelegt, self._alle_topics())

    def ankuendigen(self):
        """Discovery + aktuelle Zustände senden (bei jeder (Neu-)Verbindung und wenn HA neu startet)."""
        with self.lock:
            self.mqtt.publish(AVAIL, "online", retain=True)
            self._discovery_zentrale()
            for sn in self.sensoren:
                self._discovery_fenster(sn)
            for sn in self.handsender:
                self._discovery_handsender(sn)
            for alt in set(lade_json(self.f_angelegt, [])) - set(self._alle_topics()):
                self.mqtt.publish(alt, "", retain=True)
                log(f"Entität entfernt: {alt}")
            self._merke_angelegt()
            time.sleep(0.5)  # HA kurz Zeit geben, die Entitäten anzulegen
            for sn in self.fenster:
                self._pub_fenster(sn)
            if self.zentrale:
                self._pub(f"{P}/zentrale/status", self.zentrale, retain=True)
            if self.alarm:
                self._pub(f"{P}/zentrale/alarm", self.alarm, retain=True)
            self.mqtt.publish(f"{P}/funk", "ON" if self.funk else "OFF", retain=True)
            log(f"Home Assistant: Zentrale, {len(self.sensoren)} Fenster/Türen, {len(self.handsender)} Handsender")

    def on_message(self, topic, payload):
        if topic == f"{D}/status" and payload == b"online":
            log("Home Assistant neu gestartet – kündige Entitäten erneut an")
            threading.Thread(target=self.ankuendigen, daemon=True).start()


def main():
    opt = lade_json(os.environ.get("EIMSIG_OPTIONS", "/data/options.json"), None)
    if opt is None:
        sys.exit("Keine Optionen gefunden (EIMSIG_OPTIONS)")
    os.makedirs(DATA, exist_ok=True)
    log(f"eimsig2mqtt {VERSION} – nur lesend, sendet nichts an die Alarmanlage")
    mqtt = MQTT(os.environ.get("MQTT_HOST", "localhost"), os.environ.get("MQTT_PORT") or 1883,
                os.environ.get("MQTT_USER"), os.environ.get("MQTT_PASSWORD"),
                client_id="eimsig2mqtt", will=(AVAIL, "offline", True), log=log)
    br = Bridge(opt, mqtt)
    mqtt.on_connect = lambda: threading.Thread(target=br.ankuendigen, daemon=True).start()
    mqtt.on_message = br.on_message
    mqtt.subscribe(f"{D}/status")
    mqtt.start()

    def ende(*_):
        log("beende")
        mqtt.stop(final=[(AVAIL, "offline", True)])
        os._exit(0)
    signal.signal(signal.SIGTERM, ende)
    signal.signal(signal.SIGINT, ende)

    replay = os.environ.get("EIMSIG_REPLAY")
    if replay:  # Testmodus: Mitschnitte statt Funk; Zeitstempel aus bursts.csv (falls vorhanden)
        import csv
        for _ in range(50):
            if mqtt.connected:
                break
            time.sleep(0.1)
        time.sleep(1)
        br.funk_status(True)
        heute = dt.date.today()
        for fn in replay.split(":"):
            ts = dt.datetime.now()
            liste = os.path.join(os.path.dirname(fn), "bursts.csv")
            if os.path.exists(liste):
                for r in csv.DictReader(open(liste, encoding="utf-8")):
                    if r["datei"] == os.path.basename(fn):
                        ts = dt.datetime.combine(heute, dt.time.fromisoformat(r["zeit"]))
            for t in ep.telegramme(open(fn, "rb").read()):
                br.handle(t, ts, 30)
            time.sleep(0.05)
        time.sleep(1)
        ende()
    host = os.environ.get("RTL_TCP_HOST") or opt.get("rtl_tcp_host")
    port = int(os.environ.get("RTL_TCP_PORT") or opt.get("rtl_tcp_port") or 1234)
    if not host:
        log("Keine rtl_tcp-Adresse konfiguriert – bitte in der Add-on-Konfiguration eintragen")
        while True:
            time.sleep(3600)
    ep.empfangen(host, port, br.handle, br.funk_status, gain=float(opt.get("gain", 40.2)), log=log)


if __name__ == "__main__":
    main()
