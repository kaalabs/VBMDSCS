# *** NOT UNDER ACTIVE DEVELOPMENT: SWITCH TO VBMDSCS2 REPOSITORY FOR ACTIVE DEVELOPMENT ***

# Domobar Control System

Modulair digitaal besturingssysteem voor de **Vibiemme Domobar Standaard/Classic**.  
Decentrale kernbesturingsmodules (ESP32) communiceren via CAN (toekomstig) en bieden lokale veiligheid.  
Een mastermodule orkestreert het geheel en levert de UI. Voor WebBLE-diagnose is een **pure CSS** dashboard aanwezig.

![Systeemoverzicht](docs/system-overview.svg)

## Belangrijkste kenmerken
1. **Veiligheid eerst** — fail-safe interlocks, energize-to-run (active-LOW), autonome safety per module.
2. **Robuustheid** — eenvoudige, testbare modules; filtering en hysterese tegen ruis/slosh.
3. **Onderhoudbaarheid** — duidelijke grenzen per module, BLE-diagnose, configuratie via `config.json`.
4. **Eenvoudig** — originele gebruikerservaring blijft leidend; nerd-features optioneel.
5. **Non-invasief** — respecteert machine; hardware-interlocks voor echte fail-safety.

## Repository-structuur
```
firmware/
  watertank_module/
    main.py                    # MicroPython 1.25 code (ESP32‑WROOM‑32E)
    water_module.py            # Core watertank functionaliteit
    dypa02yy.py               # DYP-A02YY sensor driver
    level_estimator.py         # Waterniveau berekening en filtering
    display.py                 # LCD display interface
    simple_ble.py              # Bluetooth Low Energy service
    console_test.py            # Serial console test interface
    display_test.py            # Display test routines
    config.json                # Configuratie parameters
    README.md                  # Module-specifieke documentatie
    __init__.py                # Python package definitie
lvgl-micropython-firmware/    # LVGL MicroPython firmware builds
  make.sh                     # Build script voor firmware
  image/                      # Firmware images
web-dashboard/
  watertank_module/
    watertank_module_webble.html  # Pure CSS WebBLE dashboard
    app.js                         # Dashboard JavaScript logica
    styles.css                     # Dashboard styling
    README.md                      # Dashboard documentatie
docs/
  system-overview.svg              # Systeem architectuur diagram
  quickstart-flow.svg              # Quick start stroomdiagram
  system-architecture.md           # Hardware/software architectuur
  domobar-specs.md                 # Technische specificaties
  calibration-guide.md             # Kalibratie handleiding
  configuration-reference.md       # Configuratie parameter referentie
  README.md                        # Documentatie overzicht
LICENSE                           # MIT licentie
README.md                         # Project overzicht
```

## Quick Start
![Quick Start](docs/quickstart-flow.svg)

1. **Flash** MicroPython 1.25 op ESP32‑WROOM‑32E.
2. **Upload** `firmware/watertank_module/` bestanden en optioneel `config.json`.
3. **Koppel** DYP-A02YY (UART) + interlock-relais (energize-to-run, active-LOW).
4. **Start** en **verbind** via het WebBLE-dashboard (`web-dashboard/watertank_module/watertank_module_webble.html`).
5. **Calibreer**: 
   - **Handmatig**: `CAL FULL` → tank vol; `CAL EMPTY` → minimaal niveau; check `CFG?`.
   - **Auto-calibratie**: Schakel onderhoudsmodus in → klik Auto-calibratie → volg de wizard.
6. **Configuratie**: Alle parameters instelbaar via `config.json`; zie `docs/configuration-reference.md` voor volledige referentie.

## Veiligheid
- Interlocks zijn **active-LOW** (0=run, 1=stop) en ontworpen als **energize-to-run (fail-safe)**.
- MCU-fout of reboot ⇒ standaard **safe-off**.
- Heater uit bij **LOW**; **alles uit** bij **BOTTOM**.

## WaterTank Module (ESP32‑WROOM‑32E, MicroPython 1.25)
- **Hardware**: ESP32‑WROOM‑32E microcontroller met geïntegreerde WiFi/BLE
- **Sensor**: **DYP-A02YY (UART)**, ~100 ms respons, blind zone ~30 mm
- **Filtering**: Median window + EMA (`window=5`, `ema_alpha=0.25`)
- **Drempels**: `low_pct=30`, `bottom_pct=10`, `hysteresis_pct=4`
- **Sampling**: `sample_hz=8`, timeout `1200 ms`
- **Kalibratie**: `CAL FULL`/`CAL EMPTY` (waarden persist in `config.json`)
- **Interfaces**: UART sensor, I2C display, GPIO interlocks, BLE dashboard
- **Veiligheid**: Fail-safe interlocks, active-LOW logica, energize-to-run

## Dashboards (Watertank_Module)
- **WebBLE** dashboard met:
  - Live `%` + status (OK/LOW/BOTTOM/FAULT) en kleurindicatie.
  - **Onderhoudsmodus** voor geavanceerde functies.
  - **Auto-calibratie wizard** met stapsgewijze begeleiding (FULL → EMPTY).
  - **Test modus** voor validatie en debugging.
  - Eventlog en `CFG?/INFO?` dump.
- Open in **HTTPS** context (of `http://localhost`).
- **Auto-calibratie** is beschikbaar via de onderhoudsmodus checkbox.

## Media / Demo
- **GIF/Video** plaats hier later: `docs/demo-calibration.gif` (placeholder).
- **Foto’s** van montage en bedrading in `docs/images/` (optioneel).

## Licentie
MIT — zie `LICENSE`.

---

### Changelog
- **v1.0**: Basis watertank module met ESP32‑WROOM‑32E en DYP-A02YY sensor
- **v1.1**: WebBLE dashboard toegevoegd met real-time monitoring
- **v1.2**: Uitgebreide configuratie mogelijkheden en kalibratie tools
- **v1.3**: Verbeterde documentatie en configuratie referentie toegevoegd
- **v1.4**: Auto-calibratie wizard toegevoegd via onderhoudsmodus
- **Huidig**: Domobar-specifieke defaults, fail-safe interlocks, pure CSS dashboard, auto-calibratie wizard
