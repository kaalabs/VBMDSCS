# Watertank Module Firmware (ESP32‑WROOM‑32E, MicroPython 1.25)

Firmware voor de watertankmodule (ESP32‑WROOM‑32E, MicroPython 1.25) die het waterniveau meet via een DYP‑A02YY
ultrasone sensor en interlock‑uitgangen aanstuurt.

## Features

- **Water Level Monitoring**: Ultrasone sensor met filtering en state management
- **Safety Interlocks**: Automatische uitschakeling bij lage niveaus
- **BLE Interface**: WebBluetooth dashboard communicatie
- **Configurable**: JSON-gebaseerde configuratie met persistentie

## Flashen en uploaden (ESP32‑WROOM‑32E)

1. **Flash MicroPython 1.25** op de ESP32‑WROOM‑32E (macOS voorbeeld):

   ```bash
   # Poort kan bv. /dev/tty.usbmodem1101 zijn
   esptool.py --chip esp32 --port /dev/tty.usbmodem1101 erase_flash
   esptool.py --chip esp32 --port /dev/tty.usbmodem1101 --baud 460800 write_flash -z 0x1000 micropython.bin
   ```

2. **Kopieer de firmware** naar de module:

   ```bash
   mpremote connect /dev/ttyUSB0 fs cp main.py :
   mpremote connect /dev/ttyUSB0 fs cp config.json :
   ```

   Pas `config.json` eerst aan indien nodig.

3. **Reset** het board; `main.py` start automatisch. Kalibreer daarna via het
   WebBLE-dashboard (`CAL FULL`/`CAL EMPTY`).

## BLE Quickstart

De firmware bevat `simple_ble.py`, een compacte Nordic UART‑achtige service (NUS):

- RX (WRITE): ontvangt tekstregels. Elke regel eindigt op `\n` (CRLF toegestaan).
- TX (NOTIFY): verstuurt tekst (in kleine chunks) naar de centrale.
- Apparaatnaam standaard: `VBMCSWT`.

### Voorbeeldgebruik

Voeg in `main.py` (of een testscript) het volgende toe om een simpel commando te ondersteunen:

```python
from simple_ble import SimpleBLE

ble = SimpleBLE("VBMCSWT")

def handle_command(cmd: str):
    # cmd is een enkele regel zonder \r/\n
    if cmd == "ping":
        return "pong\n"
    if cmd == "id":
        return "VBMDSCS-WT\n"
    return "ERR unknown\n"

ble.on_command = handle_command
ble.notify("ready\n")

# Laat de main‑loop draaien; BLE handelt IRQ's en queue af
while True:
    pass
```

Belangrijk:

- Sluit elke opdracht af met een newline (`\n`), anders wordt deze niet verwerkt.
- Lange inkomende regels worden begrensd (accumulator ~512 tekens); voorkom excessief lange commando's.
- Uitgaande data wordt gechunked (18 bytes) en gequeue'd met eenvoudige coalescing.
- Verzendsnelheid beperken: via `ble_send_interval_ms` (default 1000 ms) wordt maximaal 1 notify per interval gestuurd om BLE te ontzien.

### Testen met nRF Connect (iOS/Android)

1. Installeer nRF Connect en open de Scan‑tab.
2. Zoek en selecteer het device met naam `VBMCSWT` en maak verbinding.
3. Vind de service met UUID `6E400001‑B5A3‑F393‑E0A9‑E50E24DCCA9E` (Nordic UART Service).
4. Karakteristieken:

   - TX (Notify): `6E400003‑B5A3‑F393‑E0A9‑E50E24DCCA9E` → schakel Notifications in.
   - RX (Write):  `6E400002‑B5A3‑F393‑E0A9‑E50E24DCCA9E` → schrijf tekst.

5. Stuur `ping\n` via de RX‑characteristic. Je zou `pong` als notificatie moeten ontvangen.
6. Stuur `id\n` en verwacht `VBMDSCS-WT`.

### BLE tips (ESP32‑WROOM‑32E / MicroPython 1.25)

- Advertentie‑payload is max. 31 bytes. Zet services eerst en gebruik een verkorte naam indien nodig.
- Gebruik connectable advertising. De firmware regelt dit automatisch.
- WebBluetooth vereist HTTPS of `http://localhost`. Dashboard: `web-dashboard/watertank_module/watertank_module_webble.html`.
