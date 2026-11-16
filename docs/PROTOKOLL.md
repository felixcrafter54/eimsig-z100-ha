# EiMSIG EM-Z100 – Funkprotokoll (868,3 MHz)

Ergebnis eigener Mitschnitte mit einem RTL-SDR (1,024 MS/s, Mittenfrequenz 868,3 MHz) an einer EM-Z100 mit
Fenstersensoren und Handsendern. Alles hier ist beobachtet, nicht vom Hersteller dokumentiert.
Seriennummern in den Beispielen sind erfunden.

## Physikalische Schicht
- **OOK/ASK** genau auf 868,3 MHz.
- Codierung wie Microchip HCS/KeeLoq: **23 Präambelpulse** (TE ≈ 400 µs, 50 %), **4 ms** Pause (10 TE),
  danach **66 Bit PWM** mit Periode 3 TE = 1,2 ms.
- **Kurzer Puls (1 TE) = 1**, langer Puls (2 TE) = 0.
- Jedes Telegramm wird 5–8× wiederholt (Burst ≈ 0,5–0,85 s).

## Zwei Telegrammarten
Bits in Sendereihenfolge 0…65. Mehrbit-Felder außer Byte 0 werden **LSB zuerst** gelesen.

| Bits | Klartext-Telegramm (Bits 60–63 = `0000`) | Rollendes Telegramm (Bits 60–63 ≠ `0000`) |
|---|---|---|
| 0–7 | **Zustandscode** (als Zahl MSB zuerst) | verschlüsselt (KeeLoq-Hopping-Code) |
| 8 | Nachmeldung: 0 = erste Meldung, 1 = Wiederholung | verschlüsselt |
| 9–15 | 0 | verschlüsselt |
| 16–19 | **Prüfsumme** (siehe unten) | verschlüsselt |
| 20–23 | 0 | verschlüsselt |
| 24–31 | **Gerätetyp**: `11100100` (0x27) Fenstersensor, `11010100` (0x2B) Zentrale | verschlüsselt |
| 32–59 | **Seriennummer** (28 Bit) | **Seriennummer** (28 Bit, Klartext) |
| 60–63 | `0000` | **Tasten** (Klartext) |
| 64–65 | Statusbits (meist `11`, Bedeutung offen – evtl. Batterie) | Statusbits (V-low, Repeat) |

### Prüfsumme
Für k = 16…19 gilt: Bit k = XOR aller übrigen Bits i (0…65, ohne 16–19) mit i ≡ k (mod 4).
Bestätigt an allen beobachteten Klartext-Telegrammen von Sensoren und Zentrale.

## Fenstersensoren (Typ 0x27)
Byte 0 ist ein **Code**, kein Messwert (165 und 166 bedeuten Verschiedenes). Bisher beobachtet:

| Code | Kippfenster „Familie A“ | Kippfenster „Familie B“ | 2-Stellungs-Sensor / Tür |
|---|---|---|---|
| 38 | zu | – | – |
| 165 | gekippt | – | zu (Familie A) |
| 166 | – | zu | – |
| 101 | – | gekippt | zu (Familie B) |
| 255 | offen | offen | offen |

Sensoren, die an der Zentrale auf **2 Stellungen** eingestellt sind (Türen, Fenster ohne Kippen), senden im
geschlossenen Zustand den „gekippt“-Code ihrer Familie; die Zentrale wertet ihn als „zu“. Welche Bedeutung gilt,
legt also die Kalibrierung in der Zentrale fest – das Add-on lernt sie aus dem Zentralen-Status (siehe unten).

Ablauf bei einer Änderung: Telegramm mit Bit 8 = 0, danach meist 1–2 Nachmeldungen (Bit 8 = 1) nach ~10–40 s.
Ein periodisches Lebenszeichen wurde in 20 Minuten nicht beobachtet.

## Zentrale
**Klartext-Status (Typ 0x2B)** – Byte 0 = Gesamtstatus wie im Display:

| Code | Status |
|---|---|
| 38 | grün (alles zu) |
| 165 | gelb (mindestens ein Fenster gekippt) |
| 255 | rot (mindestens ein Fenster offen) |

Die Zentrale sendet ihn **~0,8 s nach jeder Erstmeldung eines eigenen Sensors** (nicht bei Nachmeldungen, nie bei
fremden Sensoren) und zusätzlich etwa alle 30 s.

**Rollendes Telegramm** – Seriennummer = Klartext-Seriennummer mit gesetztem Bit 59 (z. B. 90000123 →
90000123 + 2²⁷). Die **Tastenbits** enthalten den Scharf-Zustand:

| Tasten (Bits 60–63) | Bedeutung |
|---|---|
| `1011` | scharf |
| `1001` | unscharf |

Gesendet ~1 s nach jedem Scharf-/Unscharfschalten (Handsender oder Bedienteil) und etwa alle 30 s.
Der Zustand „Alarm“ ist noch nicht beobachtet.

## Handsender
Rollende Telegramme mit eigener Seriennummer. Tasten: `0100` = rote Taste (scharf), `1000` = grüne Taste (unscharf).
Ein Tastendruck erzeugt meist zwei Varianten (Repeat-Bit). Die Zentrale antwortet ~1 s später mit ihrem
rollenden Status-Telegramm.

## Erkennen eigener Geräte
Auf 868,3 MHz funken auch andere Systeme (z. B. FSK-Bursts von Homematic, Funkfernbedienungen der Nachbarn).
Eigene Geräte lassen sich daran erkennen, dass die **Zentrale innerhalb von ~1 s antwortet** – auf Sensoren mit
ihrem Klartext-Status, auf Handsender mit ihrem rollenden Telegramm (passender Scharf-Zustand).
