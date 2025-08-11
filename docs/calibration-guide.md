# Calibration Guide — WaterTank Module

Deze handleiding beschrijft de auto-calibratieprocedure voor de WaterTank kernbesturingsmodule.

## Voorbereiding
1. Zorg dat de module is aangesloten op de Domobar en de sensor correct gemonteerd is.
2. Start de module op.
3. Open het **Domobar WebBLE Dashboard** (pure CSS versie).

## Calibratieprocedure

### CAL FULL
1. Vul de watertank volledig.
2. Wacht tot het wateroppervlak stabiel is.
3. Klik op de knop **CAL FULL** in het dashboard.
4. De module slaat de huidige sensorwaarde op als `cal_full_mm`.

### CAL EMPTY
1. Leeg de watertank tot het minimale niveau waarop de pomp nog net water kan aanzuigen (geen lucht).
2. Wacht tot het wateroppervlak stabiel is.
3. Klik op **CAL EMPTY** in het dashboard.
4. De module slaat de huidige sensorwaarde op als `cal_empty_mm`.

## CAL CLEAR (optioneel)
- Herstelt de calibratiewaarden naar `None`.
- Bij volgende run worden startwaarden uit `config.json` gebruikt of auto-learn.

## Verifiëren
1. Klik op **INFO?** in het dashboard.
2. Controleer of `cal_full_mm` en `cal_empty_mm` zijn bijgewerkt.
3. Beweeg het waterniveau rond LOW/BOTTOM en verifieer dat de interlocks correct schakelen.

## Tips
- Voer calibratie uit in normale gebruiksomgeving van de machine (temperatuur, trillingen).
- Vermijd schuim of turbulentie tijdens meten.
- Herhaal calibratie na sensorverplaatsing of tankvervanging.
