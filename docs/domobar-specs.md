# Vibiemme Domobar Standaard/Classic — Technische Specificaties

## Afmetingen & constructie
- **Type:** Enkelboiler espressomachine
- **Boiler:** Koperen boiler
- **Watertankhoogte:** ~196 mm
- **Watertankcapaciteit:** ~1,3 liter
- **Watertanksensor (retrofit):** DYP-A02YY (UART)

## Elektrische kenmerken
- **Pomp:** Vibratiepomp 230V AC
- **Verwarmingselement:** ± 1200 W
- **Bedieningslogica origineel:** Mechanische pressostaat voor boilerdruk

## Sensorplaatsing
- Ultrasonische sensor in de bovenkap gericht op wateroppervlak.
- Sensor blind zone: ~30 mm onder transducer.

## Aanbevolen parameters voor WaterTank Module
- **min_mm:** 30
- **max_mm:** 220
- **cal_full_mm:** 50 (initieel; on-site calibreren)
- **cal_empty_mm:** 190 (initieel; on-site calibreren)
- **low_pct:** 30%
- **bottom_pct:** 10%
- **hysteresis_pct:** 4%
- **sample_hz:** 8
- **timeout_ms:** 1200

## Veiligheidsadvies
- Interlock relais plaatsen in energize-to-run configuratie.
- Heater altijd uitschakelen bij LOW.
- Zowel pomp als heater uitschakelen bij BOTTOM of FAULT.
