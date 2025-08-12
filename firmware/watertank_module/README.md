# Watertank Module Firmware

Firmware voor de watertankmodule (ESP32) die het waterniveau meet via een DYP-A02YY
ultrasone sensor en interlock-uitgangen aanstuurt.

## Configuratie

Instellingen staan in `config.json`. Pas waarden zoals `sample_hz`, `low_pct` en
`allow_pump_at_low` aan voordat je de bestanden naar de MCU kopieert.
Wordt `config.json` weggelaten, dan gebruikt de firmware de ingebouwde defaults.

## Flashen en uploaden

1. **Flash MicroPython** op de ESP32 (voorbeeld):
   ```
   esptool.py --chip esp32 --port /dev/ttyUSB0 erase_flash
   esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 460800 write_flash -z 0x1000 micropython.bin
   ```

2. **Kopieer de firmware** naar de module:
   ```
   mpremote connect /dev/ttyUSB0 fs cp main.py :
   mpremote connect /dev/ttyUSB0 fs cp config.json :
   ```
   Pas `config.json` eerst aan indien nodig.

3. **Reset** het board; `main.py` start automatisch. Kalibreer daarna via het
   WebBLE-dashboard (`CAL FULL`/`CAL EMPTY`).
