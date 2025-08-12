# Watertank Module Dashboard

WebBLE-dashboard voor diagnose en kalibratie van de watertankmodule.

## Doel

- Toont het actuele waterniveau en de status (OK/LOW/BOTTOM/FAULT).
- Biedt knoppen voor kalibratie en configuratie.

## Lokaal draaien

1. Zorg voor een browser met WebBluetooth (Chrome/Edge).
2. Start een lokale server:
   ```
   cd web-dashboard/watertank_module
   python3 -m http.server 8000
   ```
3. Open `http://localhost:8000/watertank_module_webble.html` en klik op *Connect*.
   WebBluetooth vereist een veilige context; `localhost` voldoet hiervoor.
