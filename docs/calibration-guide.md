# Calibration Guide — WaterTank Module

Deze handleiding beschrijft de auto-calibratieprocedure voor de WaterTank kernbesturingsmodule.

## Voorbereiding
1. Zorg dat de module is aangesloten op de Domobar en de sensor correct gemonteerd is.
2. Start de module op.
3. Open het **Domobar WebBLE Dashboard** (pure CSS versie).

## Calibratieprocedure

### Optie 1: Handmatige Calibratie (Expert Modus)

#### CAL FULL
1. Vul de watertank volledig.
2. Wacht tot het wateroppervlak stabiel is.
3. Klik op de knop **CAL FULL** in het dashboard.
4. De module slaat de huidige sensorwaarde op als `cal_full_mm`.

#### CAL EMPTY
1. Leeg de watertank tot het minimale niveau waarop de pomp nog net water kan aanzuigen (geen lucht).
2. Wacht tot het wateroppervlak stabiel is.
3. Klik op **CAL EMPTY** in het dashboard.
4. De module slaat de huidige sensorwaarde op als `cal_empty_mm`.

### Optie 2: Auto-Calibratie (Onderhoudsmodus)

#### Stap 1: Activeer Onderhoudsmodus
1. Schakel **Onderhoudsmodus** in via de checkbox in het dashboard.
2. De **Auto-Calibratie** knop wordt nu zichtbaar en actief.

#### Stap 2: Start Auto-Calibratie
1. Klik op de **Auto-Calibratie** knop.
2. Het stappenpaneel wordt geopend met instructies.

#### Stap 3: FULL Kalibratie
1. **Vul de tank volledig** en wacht tot het niveau stabiel is.
2. Klik op **"Markeer FULL"**.
3. Het systeem slaat de huidige sensorwaarde op als `cal_full_mm`.

#### Stap 4: EMPTY Kalibratie
1. **Leeg de tank** tot minimaal niveau en plaats hem terug.
2. Wacht tot het niveau stabiel is.
3. Klik op **"Markeer EMPTY"**.
4. Het systeem slaat de huidige sensorwaarde op als `cal_empty_mm`.

#### Stap 5: Voltooiing
1. Na beide stappen wordt automatisch `CFG?` uitgevoerd.
2. De kalibratie is voltooid en opgeslagen.
3. Het stappenpaneel sluit automatisch.

#### Navigatie
- **Terug**: Ga terug naar vorige stap (alleen beschikbaar na stap 1)
- **Annuleren**: Stop de auto-calibratie en sluit het paneel
- **Volgende**: Ga naar volgende stap of voltooi kalibratie

## CAL CLEAR (optioneel)
- Herstelt de calibratiewaarden naar `None`.
- Bij volgende run worden startwaarden uit `config.json` gebruikt of auto-learn.

## Verifiëren
1. Klik op **INFO?** in het dashboard.
2. Controleer of `cal_full_mm` en `cal_empty_mm` zijn bijgewerkt.
3. Beweeg het waterniveau rond LOW/BOTTOM en verifieer dat de interlocks correct schakelen.

## Tips
- **Auto-calibratie** is aanbevolen voor nieuwe installaties en onderhoud.
- **Handmatige calibratie** is geschikt voor snelle aanpassingen en debugging.
- Voer calibratie uit in normale gebruiksomgeving van de machine (temperatuur, trillingen).
- Vermijd schuim of turbulentie tijdens meten.
- Herhaal calibratie na sensorverplaatsing of tankvervanging.
- De onderhoudsmodus biedt extra functionaliteit voor professioneel gebruik.
