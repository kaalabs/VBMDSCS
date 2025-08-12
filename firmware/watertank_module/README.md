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
   ```
   mpremote connect /dev/ttyUSB0 fs cp main.py :
   mpremote connect /dev/ttyUSB0 fs cp config.json :
   ```
   Pas `config.json` eerst aan indien nodig.

3. **Reset** het board; `main.py` start automatisch. Kalibreer daarna via het
   WebBLE-dashboard (`CAL FULL`/`CAL EMPTY`).

### BLE tips (ESP32‑WROOM‑32E / MicroPython 1.25)
- Advertentie‑payload is max. 31 bytes. Zet services eerst en gebruik een verkorte naam indien nodig.
- Gebruik connectable advertising. De firmware regelt dit automatisch.
- WebBluetooth vereist HTTPS of `http://localhost`. Dashboard: `web-dashboard/watertank_module/watertank_module_webble.html`.
