# System Architecture — Domobar Control System

## Overzicht

Het Domobar Control System is een modulair digitaal besturingssysteem voor de Vibiemme Domobar Standaard/Classic espressomachine.  
Elk kernbesturingselement heeft een **decentrale kernbesturingsmodule** die autonoom kan functioneren.  
Een centrale **mastermodule** met touchscreen zal in de toekomst de orchestratie en geavanceerde functies verzorgen.

## Hoofdkenmerken

1. **Veiligheid** (prioriteit #1)
2. **Robuustheid**
3. **Onderhoudbaarheid**
4. **Gebruiksgemak**
5. **Non-invasief** ontwerp (behoud originele gebruikerservaring)

## Module-overzicht

| Module            | MCU                    | Sensor/Interface            | Functie |
|-------------------|-----------------------|-----------------------------|---------|
| WaterTank         | ESP32-WROOM-32E       | DYP-A02YY (UART)            | Niveaubewaking + interlocks |
| Pomp              | ESP32-WROOM-32E       | Druksensor + SSR            | Drukprofiling, pompregeling |
| Temperatuur/Boiler| ESP32-WROOM-32E       | PT100/NTC + SSR             | PID-temperatuurregeling |

## Communicatie

- **CAN bus** (OpenCAN of lichte variant) voor master–module communicatie.
- **BLE** per module voor status, debug en calibratie (via WebBLE dashboard).

Voor de watertankmodule wordt een compacte Nordic UART‑achtige service gebruikt voor tekstgebaseerde status en commando’s. Zie de BLE Quickstart in `firmware/watertank_module/README.md` voor voorbeeldgebruik en het testen met nRF Connect.

## Veiligheidsconcept

- **Active-LOW energize-to-run** interlock logica: elk relais schakelt uit naar een veilige toestand bij verlies van MCU-signaal.
- Autonome fail-safe logica in elke module:
  - **OK**: pomp & heater toegestaan.
  - **LOW**: pomp optioneel, heater uit.
  - **BOTTOM**: pomp & heater uit.
  - **FAULT**: alles uit.

## Toekomstige uitbreidingen

- Integratie van mastermodule met touchscreen UI.
- Logging en cloud-export van statusdata.
- Extra modules voor kleppenregeling en onderhoudswaarschuwingen.
