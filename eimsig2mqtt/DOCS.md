# EiMSIG Alarmanlage

Liest die Funktelegramme einer **EiMSIG EM-Z100** über einen RTL-SDR-Stick mit und legt per **MQTT Discovery**
alles in Home Assistant an. Das Add-on ist **nur lesend** – es sendet nichts an die Alarmanlage.

## Voraussetzungen
- **RTL-SDR-Stick** (RTL2832U, z. B. mit R820T/R828D-Tuner), entweder
  - an einem anderen Rechner mit **rtl_tcp** (`rtl_tcp -a 0.0.0.0 -p 1234`) – Quelle `rtl_tcp`, oder
  - direkt am Home-Assistant-Gerät – Quelle `usb` (**experimentell**).
- **MQTT-Broker**: am einfachsten das Mosquitto-Add-on mit eingerichteter MQTT-Integration. Dann sind keine
  Zugangsdaten nötig. Einen anderen Broker trägst du unter `mqtt_host` usw. ein.
- Empfang: Der Stick sollte im Haus stehen, idealerweise zentral. Pegel ab etwa +15 dB reichen.

## Erste Schritte
1. **Quelle** wählen und bei `rtl_tcp` die Adresse eintragen → **Starten**.
2. Im Tab **Protokoll** erscheint nach spätestens ~30 s `Zentrale erkannt: …`.
3. Jedes **Fenster** einmal öffnen und schließen → `Neues Gerät angelegt: Fenster …`.
4. Jeden **Handsender** zweimal drücken (scharf, unscharf) → `Neues Gerät angelegt: Handsender …`.
5. In **Einstellungen → Geräte & Dienste → MQTT** die Geräte umbenennen und Räumen zuordnen.

Ein Gerät wird erst angelegt, wenn die **Zentrale zweimal darauf reagiert** hat. Sensoren und Fernbedienungen
der Nachbarn (auf 868 MHz funkt einiges) werden so nie angelegt; sie erscheinen höchstens in der
Diagnose-Entität „Unbekanntes Gerät“.

## Was in Home Assistant erscheint
| Gerät | Entitäten |
|---|---|
| **EiMSIG Zentrale** | `Status` (grün/gelb/rot), `Alarmanlage` (scharf/unscharf/unbekannt), `Scharf` (an/aus); Diagnose: `Funkempfang`, `Unbekanntes Gerät` |
| **je Fenster/Tür** | Hauptentität (an = offen oder gekippt), `Zustand` (zu/gekippt/offen) mit Attributen Code, Pegel, Zeit, Quelle |
| **je Handsender** | Ereignis-Entität `Taste` mit `scharf` / `unscharf` / `andere` |

Beispiel-Automation:
```yaml
trigger:
  - platform: state
    entity_id: event.handsender_1_taste
condition:
  - condition: state
    entity_id: event.handsender_1_taste
    attribute: event_type
    state: unscharf
action:
  - service: notify.mobile_app_handy
    data:
      message: "Jemand ist nach Hause gekommen – Alarmanlage unscharf"
```

## Konfiguration
| Option | Bedeutung |
|---|---|
| `quelle` | `rtl_tcp` (Stick an anderem Rechner) oder `usb` (Stick hier, experimentell) |
| `rtl_tcp_host`, `rtl_tcp_port` | rtl_tcp-Server (nimmt nur **einen** Client gleichzeitig an) |
| `usb_geraet` | Nummer des Sticks, wenn mehrere angeschlossen sind |
| `gain` | Empfangsverstärkung in dB (Start: 40,2) |
| `geraete_automatisch_anlegen` | Geräte automatisch anlegen (siehe oben) |
| `zentrale_seriennr` | Nur nötig, wenn mehrere EiMSIG-Zentralen in Reichweite sind |
| `sensoren` | Optional: Seriennummer, Name, Typ fest vorgeben (`kipp`, `zwei_stellungen`, `tuer`, `auto`) |
| `handsender` | Optional: Seriennummer und Name fest vorgeben |
| `mqtt_*` | Optional: eigener MQTT-Broker |

`tuer` sorgt dafür, dass HA eine Tür statt eines Fensters anzeigt. `zwei_stellungen`/`tuer` werten alles außer
„offen“ als „zu“ – das lernt das Add-on aber ohnehin von der Zentrale.

### Zu / gekippt / offen
Jeder Sensor sendet einen Code, dessen Bedeutung die Zentrale bei der Kalibrierung festgelegt hat. Das Add-on
**lernt diese Bedeutung laufend von der Zentrale**: Etwa 0,8 s nach jeder Sensormeldung sendet die Zentrale ihren
Gesamtstatus. „grün“ heißt sicher „zu“, „gelb“ heißt „gekippt“, wenn alle anderen Fenster zu sind. Bis ein Code
gelernt ist, gilt eine Standardregel (siehe Protokoll). Meldet die Zentrale „grün“, werden alle Fenster auf „zu“
gesetzt – so korrigiert sich eine verpasste Meldung von selbst.

### Scharf / unscharf
Kommt aus dem rollenden Telegramm der Zentrale. Sie sendet es nach jedem Schalten (Handsender oder Bedienteil) und
etwa alle 30 s – nach dem Start ist der Zustand also spätestens nach ~30 s bekannt. Für Automationen ist die Entität
**Alarmanlage** maßgeblich, nicht das Handsender-Ereignis (die Zentrale kann einen Tastendruck verpassen).

## Gespeicherte Daten
Unter `/data` (bleibt bei Updates erhalten): `geraete.json` (erkannte Zentrale und Geräte), `kalibrierung.json`
(gelernte Codes), `zustand.json` (letzte Zustände). Zum Zurücksetzen das Add-on deinstallieren und neu installieren.

## MQTT-Topics
| Topic | Inhalt |
|---|---|
| `eimsig2mqtt/status` | `online` / `offline` |
| `eimsig2mqtt/funk` | `ON` / `OFF` (Verbindung zum rtl_tcp) |
| `eimsig2mqtt/fenster/<seriennr>` | `{"zustand": "zu", "code": 38, "pegel": 40.1, "zeit": "…", "quelle": "funk"}` |
| `eimsig2mqtt/zentrale/status` | `{"status": "grün", "code": 38, …}` |
| `eimsig2mqtt/zentrale/alarm` | `{"zustand": "scharf", "tasten": "1011", …}` |
| `eimsig2mqtt/handsender/<seriennr>` | `{"event_type": "scharf", "tasten": "0100"}` |
| `eimsig2mqtt/unbekannt` | zuletzt gesehenes unbekanntes Gerät |

## Fehlersuche
- **„rtl_tcp: … neuer Versuch in 5 s“** – Adresse/Port prüfen; läuft schon ein anderes Programm am rtl_tcp?
- **Zentrale wird nicht erkannt** – Empfang prüfen (Stick näher an die Zentrale, `gain` erhöhen).
- **Fenster wird nicht angelegt** – Fenster öffnen *und* schließen; im Protokoll muss „Zentrale hat reagiert“ stehen.
- **Alarmanlage zeigt `unbekannt`** – bitte Protokollzeile mit „Tasten …“ als Issue melden (vermutlich Alarm-Code).
