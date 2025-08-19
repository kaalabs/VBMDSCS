# Watertank Module Dashboard

WebBLE-dashboard voor diagnose en kalibratie van de watertankmodule.

## Doel

- Toont het actuele waterniveau en de status (OK/LOW/BOTTOM/FAULT).
- Biedt knoppen voor kalibratie en configuratie.

## Lokaal draaien

1. Zorg voor een browser met WebBluetooth (Chrome/Edge).
2. Start een lokale server:

   ```bash
   cd web-dashboard/watertank_module
   python3 -m http.server 8000
   ```

3. Open `http://localhost:8000/watertank_module_webble.html` en klik op *Connect*.
   WebBluetooth vereist een veilige context; `localhost` voldoet hiervoor.

## WebBluetooth testen (NUS)

Deze pagina gebruikt een Nordic UART‑achtige service om met de firmware te praten. Zie ook de BLE Quickstart in `firmware/watertank_module/README.md`.

### Basisstappen

1. Start de firmware met `SimpleBLE` actief (standaard naam `VBMCSWT`).
2. Klik op *Connect* en selecteer het apparaat met die naam.
3. Gebruik het invoerveld om commando’s te sturen. Eindig elk commando met `\n`.

### Snelle testcommando’s

- `ping\n` → verwacht antwoord `pong`.
- `id\n` → verwacht module‑ID, bv. `VBMDSCS-WT`.

### Tips

- Als connectie verbreekt, herlaad de pagina of klik opnieuw op *Connect*.
- Voor Android kan *Location* en Bluetooth aanstaan vereist zijn voor een scan.
