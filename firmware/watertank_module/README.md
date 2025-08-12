# Watertank Module Firmware (ESP32‑S3, MicroPython 1.25)

Firmware voor de watertankmodule (ESP32‑S3, MicroPython 1.25) die het waterniveau meet via een DYP‑A02YY
ultrasone sensor en interlock‑uitgangen aanstuurt.

## Configuratie

Instellingen staan in `config.json`. Pas waarden zoals `sample_hz`, `low_pct` en
`allow_pump_at_low` aan voordat je de bestanden naar de MCU kopieert.
Wordt `config.json` weggelaten, dan gebruikt de firmware de ingebouwde defaults.

## Flashen en uploaden (ESP32‑S3)

1. **Flash MicroPython 1.25** op de ESP32‑S3 (macOS voorbeeld):
   ```bash
   # Poort kan bv. /dev/tty.usbmodem1101 zijn
   esptool.py --chip esp32s3 --port /dev/tty.usbmodem1101 erase_flash
   esptool.py --chip esp32s3 --port /dev/tty.usbmodem1101 --baud 460800 write_flash -z 0x0 micropython.bin
   ```

2. **Kopieer de firmware** naar de module:
   ```bash
   PORT=$(ls -1 /dev/tty.* | grep -Ei 'usb|slab|wch' | head -n 1)
   # Package-bestanden
   mpremote connect $PORT fs mkdir watertank_module || true
   for f in __init__.py dypa02yy.py level_estimator.py simple_ble.py water_module.py; do \
     mpremote connect $PORT fs cp firmware/watertank_module/$f :watertank_module/$f; done
   # Entry en config
   mpremote connect $PORT fs cp firmware/watertank_module/main.py :
   mpremote connect $PORT fs cp firmware/watertank_module/config.json :
   ```
   Pas `config.json` eerst aan indien nodig.

3. **Reset** het board; `main.py` start automatisch. Kalibreer daarna via het
   WebBLE‑dashboard (`CAL FULL` / `CAL EMPTY`).

### BLE tips (ESP32‑S3 / MicroPython 1.25)
- Advertentie‑payload is max. 31 bytes. Zet services eerst en gebruik een verkorte naam indien nodig.
- Gebruik connectable advertising. De firmware regelt dit automatisch.
- WebBluetooth vereist HTTPS of `http://localhost`. Dashboard: `web-dashboard/watertank_module/watertank_module_webble.html`.
