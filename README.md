<p align="center">
  <img src="eimsig2mqtt/logo.png" alt="EiMSIG Alarmanlage für Home Assistant" width="400">
</p>

<h1 align="center">EiMSIG EM-Z100 für Home Assistant</h1>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Ffelixcrafter54%2Feimsig-z100-ha">
    <img src="https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg" alt="Repository zu Home Assistant hinzufügen">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Home%20Assistant-Add--on-41BDF5?logo=home-assistant&logoColor=white" alt="Home Assistant Add-on">
  <img src="https://img.shields.io/badge/Architektur-amd64%20%7C%20aarch64%20%7C%20armv7-blue" alt="Architekturen">
  <img src="https://img.shields.io/badge/Funk-868%2C3%20MHz-orange" alt="868,3 MHz">
  <img src="https://img.shields.io/github/license/felixcrafter54/eimsig-z100-ha" alt="Lizenz">
</p>

Liest die Funk-Alarmzentrale **EiMSIG EM-Z100** und ihre Fenstersensoren mit einem günstigen **RTL-SDR-Stick** mit
und bringt alles automatisch in Home Assistant – **ohne Eingriff in die Anlage**. Das Add-on hört nur zu und sendet
nichts; die Alarmfunktion bleibt völlig unabhängig.

## Was du bekommst

| | |
|---|---|
| 🪟 **Fenster & Türen** | Jeder Sensor als eigenes Gerät: **zu / gekippt / offen** |
| 🚦 **Zentrale** | Gesamtstatus **grün / gelb / rot** wie im Display |
| 🛡️ **Alarmanlage** | **scharf / unscharf** – egal ob per Handsender oder am Bedienteil geschaltet |
| 🔑 **Handsender** | Jeder Tastendruck als Ereignis – ideal für Automationen (z. B. „wer hat unscharf geschaltet?“) |
| ✨ **Automatisch** | Zentrale, Sensoren und Handsender werden selbst erkannt – Nachbargeräte bleiben draußen |

## Installation

1. Auf den Button oben klicken (oder in Home Assistant: **Einstellungen → Add-ons → Add-on-Store → ⋮ → Repositories**
   und `https://github.com/felixcrafter54/eimsig-z100-ha` hinzufügen).
2. **EiMSIG Alarmanlage** im Store öffnen → **Installieren**.
3. Tab **Konfiguration**: Adresse deines **rtl_tcp**-Servers eintragen (oder Quelle `usb`, wenn der Stick direkt am
   Home-Assistant-Gerät steckt).
4. **Starten** – fertig. Die Geräte erscheinen unter **Einstellungen → Geräte & Dienste → MQTT**.

**Voraussetzungen:** ein RTL-SDR-Stick (z. B. RTL2832U/R820T) und ein MQTT-Broker (am einfachsten das offizielle
**Mosquitto**-Add-on mit MQTT-Integration – die Zugangsdaten holt sich das Add-on dann selbst).

### Geräte anlernen – ohne Seriennummern zu suchen
- **Fenster:** einmal öffnen und wieder schließen.
- **Handsender:** zweimal eine Taste drücken (z. B. scharf, dann unscharf).

Sobald die Zentrale zweimal auf ein Gerät reagiert hat, legt das Add-on es an („Fenster 5033…“, „Handsender 1274…“).
Umbenennen und Räumen zuordnen kannst du sie direkt in Home Assistant. Ob ein Fenster **kippbar** ist und welcher
Code was bedeutet, lernt das Add-on ebenfalls von der Zentrale.

Ausführliche Anleitung: [eimsig2mqtt/DOCS.md](eimsig2mqtt/DOCS.md) · Protokoll: [docs/PROTOKOLL.md](docs/PROTOKOLL.md)

## Wie funktioniert das?

Die EM-Z100 und ihre Sensoren funken auf **868,3 MHz** (OOK, KeeLoq-artige Codierung). Sensoren und Zentrale-Status
sind **Klartext** mit Prüfsumme; Handsender und der Scharf-Status nutzen Rolling Code, dessen Seriennummer und
Tastenbits aber ebenfalls lesbar sind. Das Add-on dekodiert das in reinem Python direkt aus den Rohdaten des
RTL-SDR – rtl_433 wird nicht benötigt. Details in [docs/PROTOKOLL.md](docs/PROTOKOLL.md).

## Grenzen
- Getestet mit einer EM-Z100. Andere EiMSIG-Zentralen könnten ähnlich funken – Rückmeldungen willkommen.
- Der **Alarm-Zustand** selbst ist noch nicht dekodiert; ein unbekannter Code der Zentrale erscheint als `unbekannt`.
- Bewusst **kein Schalten** aus Home Assistant: Die Rolling-Code-Telegramme sind verschlüsselt und werden nicht nachgesendet.
- Die USB-Quelle ist **experimentell**; erprobt ist der Betrieb über einen rtl_tcp-Server im Netz.

## Haftung
Privates Projekt, **nicht** mit der EiMSIG GmbH verbunden. Nutzung auf eigenes Risiko. Das Add-on ersetzt keine
Alarmanlage und keine Benachrichtigung durch sie – es ist eine Ergänzung für die Hausautomation.

Lizenz: [MIT](LICENSE)
