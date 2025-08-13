# Configuratie Referentie - VBM Domobar Watertank Module

Deze documentatie beschrijft alle configuratie parameters die beschikbaar zijn voor de VBM Domobar Watertank Module. Deze parameters kunnen worden ingesteld in het `config.json` bestand op het ESP32-S3 apparaat.

## Overzicht

De configuratie is opgedeeld in verschillende categorieën:
- **UART Configuratie** - Sensor communicatie instellingen
- **Sampling & Filtering** - Data acquisitie en verwerking
- **Tank Geometrie** - Afmetingen en plausibiliteit grenzen
- **Veiligheidsbeleid** - Waterniveau drempels en interlock logica
- **Hardware I/O** - GPIO pin configuratie en interlock schakelingen
- **Bluetooth** - BLE communicatie instellingen
- **Kalibratie** - Sensor kalibratie parameters
- **Gedrag** - Systeem gedrag en opties
- **Logging** - Debug en monitoring instellingen
- **Test Modus** - Test en validatie instellingen

## UART Configuratie

### `uart_port`
- **Type**: Integer
- **Default**: 2
- **Bereik**: 1, 2
- **Beschrijving**: MicroPython UART ID gebruikt voor de DYP-A02YY sensor. Typisch 1 of 2 op ESP32-S3.
- **Gebruik**: Stelt in welke hardware UART interface wordt gebruikt voor sensor communicatie.
- **Meer info**: [MicroPython UART Documentation](https://docs.micropython.org/en/latest/library/machine.UART.html), [ESP32 UART Hardware](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/uart.html)

### `uart_rx`
- **Type**: Integer
- **Default**: 16
- **Bereik**: 0-48 (ESP32-S3 GPIO)
- **Beschrijving**: GPIO nummer voor UART RX (sensor TX lijn).
- **Gebruik**: Verbindt met de TX uitgang van de DYP-A02YY sensor.
- **Meer info**: [ESP32 GPIO Matrix](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/gpio.html), [GPIO Pin Assignment](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/hw-reference/esp32/get-started-devkitc-v4.html)

### `uart_tx`
- **Type**: Integer
- **Default**: 17
- **Bereik**: 0-48 (ESP32-S3 GPIO)
- **Beschrijving**: GPIO nummer voor UART TX (sensor RX lijn).
- **Gebruik**: Verbindt met de RX ingang van de DYP-A02YY sensor.
- **Meer info**: [ESP32 GPIO Matrix](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/gpio.html), [GPIO Pin Assignment](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/hw-reference/esp32/get-started-devkitc-v4.html)

### `uart_baud`
- **Type**: Integer
- **Default**: 9600
- **Bereik**: 9600, 19200, 38400, 57600, 115200
- **Beschrijving**: Baudrate voor UART communicatie met de sensor.
- **Gebruik**: Moet overeenkomen met de DYP-A02YY sensor instellingen.
- **Meer info**: [UART Baud Rate Standards](https://en.wikipedia.org/wiki/Baud), [DYP-A02YY Datasheet](https://www.dfrobot.com/wiki/index.php/Waterproof_Ultrasonic_Sensor_Module_SKU:SEN0207)

## Sampling & Filtering

### `sample_hz`
- **Type**: Integer
- **Default**: 8
- **Bereik**: 1-20
- **Beschrijving**: Sensor sampling frequentie in Hertz.
- **Gebruik**: Hogere frequenties geven meer real-time updates maar verbruiken meer stroom. 8 Hz is een goede balans tussen responsiviteit en efficiëntie.
- **Meer info**: [Nyquist Sampling Theorem](https://en.wikipedia.org/wiki/Nyquist%E2%80%93Shannon_sampling_theorem), [ESP32 ADC Sampling](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/adc.html)

### `window`
- **Type**: Integer
- **Default**: 5
- **Bereik**: 3-15 (oneven getallen aanbevolen)
- **Beschrijving**: Median filter venster grootte voor ruisonderdrukking.
- **Gebruik**: Grotere vensters geven stabielere metingen maar vertragen de respons. 5 samples biedt goede ruisonderdrukking zonder significante vertraging.
- **Meer info**: [Median Filter Algorithm](https://en.wikipedia.org/wiki/Median_filter), [Signal Processing Tutorial](https://www.mathworks.com/help/signal/ug/median-filtering.html), [MicroPython Array Operations](https://docs.micropython.org/en/latest/library/array.html)

### `ema_alpha`
- **Type**: Float
- **Default**: 0.25
- **Bereik**: 0.0-1.0
- **Beschrijving**: Exponential Moving Average smoothing factor.
- **Gebruik**: Hogere waarden (dichter bij 1.0) maken het systeem responsiever maar gevoeliger voor ruis. 0.25 biedt goede stabiliteit met acceptabele respons.
- **Meer info**: [Exponential Moving Average](https://en.wikipedia.org/wiki/Moving_average#Exponential_moving_average), [EMA vs SMA Comparison](https://www.investopedia.com/ask/answers/122314/what-exponential-moving-average-ema-formula-and-how-ema-calculated.asp)

## Tank Geometrie & Plausibiliteit

### `min_mm`
- **Type**: Integer
- **Default**: 30
- **Bereik**: 20-100
- **Beschrijving**: Plausibele minimum afstand in millimeters.
- **Gebruik**: Stelt de ondergrens in voor geldige sensor metingen. 30mm is de typische blinde zone van de DYP-A02YY sensor.

### `max_mm`
- **Type**: Integer
- **Default**: 220
- **Bereik**: 150-400
- **Beschrijving**: Plausibele maximum afstand in millimeters.
- **Gebruik**: Stelt de bovengrens in voor geldige sensor metingen. Moet groter zijn dan de werkelijke tank hoogte plus een veiligheidsmarge.

## Sensor Timeout

### `timeout_ms`
- **Type**: Integer
- **Default**: 1200
- **Bereik**: 500-5000
- **Beschrijving**: Timeout in milliseconden voor geldige sensor metingen.
- **Gebruik**: Als er geen geldige meting binnen deze tijd komt, wordt de status op FAULT gezet. 1200ms is voldoende voor de meeste omstandigheden.

## Waterniveau Beleid (Percentage van Tank Volheid)

### `bottom_pct`
- **Type**: Integer
- **Default**: 10
- **Bereik**: 5-20
- **Beschrijving**: Percentage drempel voor "leeg" niveau.
- **Gebruik**: Onder deze drempel worden alle interlocks geactiveerd en wordt de machine veilig gestopt.
- **Meer info**: [Threshold Detection](https://en.wikipedia.org/wiki/Threshold_detector), [Safety Thresholds](https://www.iso.org/standard/45001.html)

### `low_pct`
- **Type**: Integer
- **Default**: 30
- **Bereik**: 15-50
- **Beschrijving**: Percentage drempel voor "laag" niveau.
- **Gebruik**: Onder deze drempel wordt de verwarming uitgeschakeld om oververhitting te voorkomen.
- **Meer info**: [Multi-Level Thresholds](https://en.wikipedia.org/wiki/Threshold_model), [Thermal Protection](https://www.omega.com/en-us/control-and-monitoring-devices/process-control-and-monitoring/process-controllers)

### `hysteresis_pct`
- **Type**: Integer
- **Default**: 4
- **Bereik**: 2-10
- **Beschrijving**: Hysteresis band in percentage om snelle toggling te voorkomen.
- **Gebruik**: Voorkomt dat de status constant wisselt rond de drempelwaarden. 4% is een goede balans tussen stabiliteit en responsiviteit.
- **Meer info**: [Hysteresis in Control Systems](https://en.wikipedia.org/wiki/Hysteresis#Control_systems), [Schmitt Trigger Principle](https://en.wikipedia.org/wiki/Schmitt_trigger), [Debouncing Techniques](https://www.arduino.cc/en/Tutorial/Debounce)

## Interlock Configuratie

### `interlock_active`
- **Type**: Boolean
- **Default**: True
- **Beschrijving**: Master interlock logica in- of uitschakelen.
- **Gebruik**: Als False, worden alle veiligheidsinterlocks genegeerd (alleen voor testen!).
- **Meer info**: [Safety Interlock Systems](https://en.wikipedia.org/wiki/Interlock), [Fail-Safe Design Principles](https://www.isa.org/standards-and-publications/isa-standards/isa-standards-committees/isa84), [Industrial Safety Standards](https://www.iso.org/standard/45001.html)

### `interlock_pin`
- **Type**: Integer
- **Default**: 15
- **Bereik**: 0-48 (ESP32-S3 GPIO)
- **Beschrijving**: GPIO die alle belastingen afsluit (master interlock).
- **Gebruik**: Active-LOW logica: 0 = toestaan, 1 = veilig (stoppen).
- **Meer info**: [Active-LOW Logic](https://en.wikipedia.org/wiki/Logic_level#Active-low_signals), [ESP32 GPIO Control](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/gpio.html)

### `pump_ok_pin`
- **Type**: Integer
- **Default**: 14
- **Bereik**: 0-48 (ESP32-S3 GPIO)
- **Beschrijving**: GPIO die de pomp toestaat.
- **Gebruik**: Active-LOW logica: 0 = pomp aan, 1 = pomp uit.
- **Meer info**: [Relay Module Wiring](https://randomnerdtutorials.com/guide-for-relay-module-with-arduino/), [ESP32 Relay Control](https://randomnerdtutorials.com/esp32-relay-module-ac-web-server/)

### `heater_ok_pin`
- **Type**: Integer
- **Default**: 27
- **Bereik**: 0-48 (ESP32-S3 GPIO)
- **Beschrijving**: GPIO die de verwarming toestaat.
- **Gebruik**: Active-LOW logica: 0 = verwarming aan, 1 = verwarming uit.
- **Meer info**: [Heater Control Systems](https://www.omega.com/en-us/control-and-monitoring-devices/process-control-and-monitoring/process-controllers), [Thermal Management](https://www.ti.com/lit/an/slva462a/slva462a.pdf)

### `use_pump_ok`
- **Type**: Boolean
- **Default**: True
- **Beschrijving**: Of de pomp interlock pin wordt gebruikt.
- **Gebruik**: Als False, wordt de pomp_ok pin genegeerd (pomp blijft veilig/uit).

### `use_heater_ok`
- **Type**: Boolean
- **Default**: True
- **Beschrijving**: Of de verwarming interlock pin wordt gebruikt.
- **Gebruik**: Als False, wordt de heater_ok pin genegeerd (verwarming blijft veilig/uit).

## Hardware I/O

### `led_pin`
- **Type**: Integer of None
- **Default**: 2
- **Bereik**: 0-48 (ESP32-S3 GPIO) of None
- **Beschrijving**: GPIO voor status LED.
- **Gebruik**: Stel in op None om de LED uit te schakelen. LED knippert om systeem status aan te geven.

## Bluetooth Configuratie

### `ble_enabled`
- **Type**: Boolean
- **Default**: True
- **Beschrijving**: Nordic UART-achtige BLE service in- of uitschakelen.
- **Gebruik**: Vereist voor WebBLE dashboard communicatie. Kan worden uitgeschakeld om stroom te besparen.
- **Meer info**: [Web Bluetooth API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Bluetooth_API), [ESP32 BLE Tutorial](https://randomnerdtutorials.com/esp32-bluetooth-low-energy-ble-arduino-ide/)

### `ble_name`
- **Type**: String
- **Default**: "VBMDSCSWT"
- **Bereik**: 1-20 karakters
- **Beschrijving**: BLE GAP/advertising apparaat naam.
- **Gebruik**: Deze naam verschijnt in de Bluetooth instellingen van je apparaat.
- **Meer info**: [ESP32 BLE Device Name](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/bluetooth/esp_gap_ble.html)

## Kalibratie Parameters

### `cal_auto_learn`
- **Type**: Boolean
- **Default**: True
- **Beschrijving**: Automatisch bijhouden van waargenomen min/max waarden.
- **Gebruik**: Als True, leert het systeem automatisch van waargenomen extremen als backstop voor ontbrekende kalibratie.
- **Meer info**: [Machine Learning Basics](https://en.wikipedia.org/wiki/Machine_learning)

### `cal_empty_mm`
- **Type**: Float
- **Default**: 190.0
- **Bereik**: 50-400
- **Beschrijving**: Initiële EMPTY kalibratie anker in millimeters.
- **Gebruik**: Startwaarde voor kalibratie. Wordt overschreven door CAL EMPTY commando.
- **Meer info**: [Ultrasonic Sensor Calibration](https://www.maxbotix.com/articles/ultrasonic-sensor-calibration.htm), [Distance Measurement Principles](https://en.wikipedia.org/wiki/Ultrasonic_sensor), [Calibration Standards](https://www.nist.gov/calibrations)

### `cal_full_mm`
- **Type**: Float
- **Default**: 50.0
- **Bereik**: 20-150
- **Bereik**: Initiële FULL kalibratie anker in millimeters.
- **Gebruik**: Startwaarde voor kalibratie. Wordt overschreven door CAL FULL commando.
- **Meer info**: [Two-Point Calibration](https://en.wikipedia.org/wiki/Calibration_curve), [Linear Interpolation](https://www.mathworks.com/help/matlab/ref/interp1.html)

## Gedrag Opties

### `allow_pump_at_low`
- **Type**: Boolean
- **Default**: True
- **Beschrijving**: Of de pomp mag draaien bij laag waterniveau.
- **Gebruik**: Als False, mag de pomp alleen draaien bij OK niveau (niet bij LOW).

## Logging Configuratie

### `log_level`
- **Type**: String
- **Default**: "info"
- **Opties**: "err", "warn", "info"
- **Beschrijving**: Logging niveau voor debug en monitoring.
- **Gebruik**: 
  - "err": Alleen fouten
  - "warn": Fouten en waarschuwingen
  - "info": Alle berichten (meest uitgebreid)
- **Meer info**: [Logging Levels](https://en.wikipedia.org/wiki/Log_level), [Python Logging](https://docs.python.org/3/howto/logging.html), [MicroPython Print Function](https://docs.micropython.org/en/latest/library/builtins.html#print), [Debugging Techniques](https://docs.micropython.org/en/latest/reference/debugging.html)

## Boot & Opslag

### `persist_path`
- **Type**: String
- **Default**: "config.json"
- **Beschrijving**: Bestandspad waar configuratie wordt opgeslagen op het apparaat.
- **Gebruik**: Meestal niet wijzigen tenzij je een andere bestandsstructuur wilt.

### `boot_grace_s`
- **Type**: Integer
- **Default**: 3
- **Bereik**: 1-10
- **Beschrijving**: Seconden na boot voordat het systeem "ready" wordt.
- **Gebruik**: Geeft tijd voor sensor stabilisatie en systeem initialisatie.

## Test Modus

### `test_period_s`
- **Type**: Integer
- **Default**: 20
- **Bereik**: 10-60
- **Beschrijving**: Periode in seconden voor één volledige synthetische sweep in TEST modus.
- **Gebruik**: Langere periodes geven meer tijd om test resultaten te observeren.
- **Meer info**: [Synthetic Data Generation](https://en.wikipedia.org/wiki/Synthetic_data), [Test Automation](https://en.wikipedia.org/wiki/Test_automation)

## Configuratie Wijzigen

### Via Dashboard
1. Verbind met het apparaat via WebBLE
2. Gebruik CFG? om huidige configuratie te bekijken
3. Gebruik CFG RESET om terug te gaan naar defaults
4. Gebruik CFG commando's om specifieke waarden te wijzigen

### Via Bestand
1. Upload een aangepaste `config.json` naar het apparaat
2. Herstart het apparaat
3. De nieuwe configuratie wordt automatisch geladen

### Via Serial Console
1. Verbind via USB-serial
2. Gebruik Python commando's om configuratie te wijzigen
3. Gebruik `save_config()` om wijzigingen op te slaan

## Aanbevolen Instellingen

### Voor Productie
```json
{
  "sample_hz": 8,
  "window": 5,
  "ema_alpha": 0.25,
  "timeout_ms": 1200,
  "interlock_active": true,
  "ble_enabled": true,
  "log_level": "warn"
}
```

### Voor Testen
```json
{
  "sample_hz": 4,
  "window": 3,
  "ema_alpha": 0.5,
  "timeout_ms": 2000,
  "interlock_active": false,
  "ble_enabled": true,
  "log_level": "info"
}
```

### Voor Debugging
```json
{
  "sample_hz": 2,
  "window": 3,
  "ema_alpha": 0.1,
  "timeout_ms": 5000,
  "interlock_active": false,
  "ble_enabled": true,
  "log_level": "info"
}
```

## Troubleshooting

### Veelvoorkomende Problemen

1. **Sensor geeft geen metingen**: Controleer UART configuratie en bekabeling
2. **Instabiele metingen**: Verhoog `window` en verlaag `ema_alpha`
3. **Interlocks werken niet**: Controleer `interlock_active` en pin configuratie
4. **BLE verbinding faalt**: Controleer `ble_enabled` en `ble_name`
5. **Systeem wordt niet ready**: Verhoog `boot_grace_s`

### Debug Commando's

- `INFO?` - Huidige status en metingen
- `CFG?` - Huidige configuratie
- `TEST START` - Start test modus
- `TEST STOP` - Stop test modus
- `TEST?` - Test status

## Algoritme Referenties

### Signal Processing & Filtering
- **[Median Filter](https://en.wikipedia.org/wiki/Median_filter)**: Ruisonderdrukking door middel van rank-order filtering
- **[Exponential Moving Average](https://en.wikipedia.org/wiki/Moving_average#Exponential_moving_average)**: Recursieve smoothing met exponentiële gewichten
- **[Nyquist Sampling](https://en.wikipedia.org/wiki/Nyquist%E2%80%93Shannon_sampling_theorem)**: Minimum sampling frequentie voor signaal reconstructie
- **[Digital Signal Processing](https://en.wikipedia.org/wiki/Digital_signal_processing)**: Theorie en praktijk van DSP algoritmes

### Control Systems & Safety
- **[Hysteresis Control](https://en.wikipedia.org/wiki/Hysteresis#Control_systems)**: Stabilisatie door dubbelzinnige drempels
- **[Fail-Safe Design](https://en.wikipedia.org/wiki/Fail-safe)**: Systemen die veilig falen
- **[Interlock Systems](https://en.wikipedia.org/wiki/Interlock)**: Veiligheidsmechanismen in industriële systemen
- **[Active-LOW Logic](https://en.wikipedia.org/wiki/Logic_level#Active-low_signals)**: Veilige signaal logica

### Embedded Systems & MicroPython
- **[ESP32 Architecture](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/)**: Officiële ESP32 documentatie
- **[MicroPython](https://docs.micropython.org/en/latest/)**: Python voor microcontrollers
- **[GPIO Programming](https://docs.micropython.org/en/latest/library/machine.Pin.html)**: Pin control en I/O
- **[UART Communication](https://docs.micropython.org/en/latest/library/machine.UART.html)**: Serial communicatie

### Bluetooth & Web Technologies
- **[Web Bluetooth API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Bluetooth_API)**: Browser-gebaseerde BLE communicatie
- **[ESP32 BLE Documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/bluetooth/)**: Officiële ESP32 Bluetooth documentatie

## Veiligheid

⚠️ **BELANGRIJK**: Wijzig nooit de interlock configuratie in productie zonder volledige kennis van de veiligheidsimplicaties. De interlocks zijn ontworpen om schade aan apparatuur en letsel te voorkomen.

- Test altijd configuratie wijzigingen in een veilige omgeving
- Verifieer dat alle veiligheidsfuncties correct werken na wijzigingen
- Documenteer alle wijzigingen voor toekomstige referentie
