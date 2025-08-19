"""WaterTank core module for ESP32‑WROOM‑32E (MicroPython).

Overzicht
---------
Deze module beheert de watertanklogica op een ESP32‑WROOM‑32E met MicroPython.
Belangrijke onderdelen:

- Configuratie en persistentie (`DEFAULT_CONFIG`, `load_config`)
- Sensorinname via UART (ruwe mm-waarde)
- Filteren en mapping naar percentage met hysterese voor de toestandsmachine
- Fail-safe aansturing van interlock/pump/heater via GPIO's
- BLE-statusupdates en eenvoudige testmodus met gesimuleerde gegevens

Dataflow (vereenvoudigd)
------------------------
UART → parse mm → (EMA) → percent → toestandsbesluit (OK/LOW/BOTTOM/FAULT)
→ outputs toepassen → status via BLE → dashboard.

Testmodus
---------
`start_test()` activeert een zaagtandpercentage binnen de gekalibreerde mm-range
zodat het dashboard en de BLE-keten zonder echte sensor kunnen worden beproefd.

Fail-safe principes (samenvatting)
----------------------------------
- Uitgangen starten in veilige stand (waarde 1) en worden bij fatal/stop altijd
  teruggezet naar veilig.
- Tijdens testmodus worden uitgangen hard naar veilig geforceerd (geen vrijgave
  op basis van pseudo-toestanden).
- Tijdens boot-grace blijft alles veilig totdat `ready=True`.
- Sensorvalidatie gebruikt een begrensde UART-buffer en markeert pas `sensor_valid=False`
  na meerdere opeenvolgende fouten, om flapperen te voorkomen.
- Fail-safe reageert sneller via configureerbare debounce (`debounce_ms`).
- Optionele hardware watchdog reset bij vastlopers.

Timing
------
De hoofdlus draait op `sample_hz`. Status wordt maximaal 1×/s verzonden om BLE te ontzien.
"""

import ujson as json
import machine
import time
import sys
import os
from machine import UART, Pin
import math
import gc
try:
    import random
except Exception:
    random = None

try:
    import bluetooth
except ImportError:
    bluetooth = None

# Direct imports
from dypa02yy import DYPA02YY
from level_estimator import (
    LevelEstimator,
    STATE_OK,
    STATE_LOW,
    STATE_BOTTOM,
    STATE_FAULT,
)
from simple_ble import SimpleBLE

# Configuration
# Belangrijkste veiligheidsrelevante opties:
# - allow_pump_at_low: standaard False (conservatief)
# - debounce_ms: kortere debounce voor snellere fail-safe respons
# - uart_buf_max: cap op UART-buffer om RAM-groei te vermijden
# - wdt_*: optionele hardware watchdog
DEFAULT_CONFIG = {
    "uart_port": 2,
    "uart_rx": 16,
    "uart_tx": 17,
    "uart_baud": 9600,
    "sample_hz": 8,
    "window": 5,
    "ema_alpha": 0.25,
    "min_mm": 30,
    "max_mm": 220,
    "timeout_ms": 1200,
    "bottom_pct": 10,
    "low_pct": 30,
    "hysteresis_pct": 4,
    "interlock_active": True,
    "interlock_pin": 15,
    "pump_ok_pin": 14,
    "heater_ok_pin": 27,
    "use_pump_ok": True,
    "use_heater_ok": True,
    "led_pin": 2,
    "ble_enabled": True,
    "ble_name": "VBMCSWT",
    "cal_auto_learn": True,
    "cal_empty_mm": 190.0,
    "cal_full_mm": 50.0,
    "allow_pump_at_low": False,
    "debounce_ms": 200,
    "uart_buf_max": 256,
    "wdt_enabled": True,
    "wdt_timeout_ms": 8000,
    "log_level": "info",
    # BLE
    "ble_send_interval_ms": 1000,
    "persist_path": "config.json",
    "boot_grace_s": 3,
    "test_period_s": 20,
    "test_pipeline": False,
    "test_allow_outputs": False,
    # Realistische UART/testinjectie-parameters
    "test_uart_chunk_min": 4,
    "test_uart_chunk_max": 12,
    "test_noise_mm": 0.0,
    "test_outlier_prob": 0.0,
    "test_dropout_prob": 0.0,
    "test_corrupt_prob": 0.0,
    "test_jitter_skip_prob": 0.0,
}

LOG_LEVELS = {"err": 0, "error": 0, "warn": 1, "info": 2}
_LOG_LEVEL = LOG_LEVELS.get(DEFAULT_CONFIG.get("log_level", "info"), 2)

def set_log_level(level):
    """Stel het globale logniveau in op "err" | "warn" | "info".

    Onbekende waarden vallen terug op "info".
    """
    global _LOG_LEVEL
    _LOG_LEVEL = LOG_LEVELS.get(level, 2)

def log(level, msg):
    """Print een genormeerde logregel indien toegestaan door het ingestelde niveau."""
    if LOG_LEVELS.get(level, 2) <= _LOG_LEVEL:
        print(f"[{level.upper()}] {msg}")

def load_config():
    """Laad configuratie uit `persist_path` en merge deze met `DEFAULT_CONFIG`.

    Veiligheid:
    - Val bij leesfouten terug op defaults.
    - Valideer en clamp kritieke parameters (ranges, thresholds, timeouts) zodat
      onrealistische waarden niet leiden tot onveilig gedrag.
    """
    try:
        with open(DEFAULT_CONFIG["persist_path"], "r") as f:
            cfg = json.loads(f.read())
        merged = DEFAULT_CONFIG.copy()
        merged.update(cfg)
    except Exception:
        merged = DEFAULT_CONFIG.copy()

    # Basic config validation and clamping for safety
    try:
        if merged["min_mm"] > merged["max_mm"]:
            merged["min_mm"], merged["max_mm"] = merged["max_mm"], merged["min_mm"]
        merged["sample_hz"] = max(1, int(merged.get("sample_hz", 8)))
        merged["timeout_ms"] = max(200, int(merged.get("timeout_ms", 1200)))
        merged["hysteresis_pct"] = max(0.0, float(merged.get("hysteresis_pct", 4)))
        merged["low_pct"] = float(merged.get("low_pct", 30))
        merged["bottom_pct"] = float(merged.get("bottom_pct", 10))
        if merged["bottom_pct"] >= merged["low_pct"]:
            merged["bottom_pct"] = max(0.0, merged["low_pct"] - 1.0)
        merged["debounce_ms"] = max(50, int(merged.get("debounce_ms", 200)))
        merged["uart_buf_max"] = max(64, int(merged.get("uart_buf_max", 256)))
        merged["wdt_timeout_ms"] = max(2000, int(merged.get("wdt_timeout_ms", 8000)))
        merged["wdt_enabled"] = bool(merged.get("wdt_enabled", True))
        # BLE rate limiter niet-negatief
        merged["ble_send_interval_ms"] = max(0, int(merged.get("ble_send_interval_ms", 1000)))
        # Clamp test injectie parameters
        def _clampf(v, a, b, d):
            try:
                x = float(v)
            except Exception:
                return d
            if x < a:
                return a
            if x > b:
                return b
            return x
        merged["test_uart_chunk_min"] = max(1, int(merged.get("test_uart_chunk_min", 4)))
        merged["test_uart_chunk_max"] = max(merged["test_uart_chunk_min"], int(merged.get("test_uart_chunk_max", 12)))
        merged["test_noise_mm"] = _clampf(merged.get("test_noise_mm", 0.0), 0.0, 10.0, 0.0)
        merged["test_outlier_prob"] = _clampf(merged.get("test_outlier_prob", 0.0), 0.0, 1.0, 0.0)
        merged["test_dropout_prob"] = _clampf(merged.get("test_dropout_prob", 0.0), 0.0, 1.0, 0.0)
        merged["test_corrupt_prob"] = _clampf(merged.get("test_corrupt_prob", 0.0), 0.0, 1.0, 0.0)
        merged["test_jitter_skip_prob"] = _clampf(merged.get("test_jitter_skip_prob", 0.0), 0.0, 1.0, 0.0)
    except Exception:
        pass

    return merged

class WaterModule:
    """Hoofdcontroller voor de watertank.

    Verantwoordelijkheden:
    - Initialisatie van GPIO, UART en BLE
    - Bijhouden van actuele sensorstatus en afgeleide toestand
    - Toepassen van fail-safe uitgangsstaten
    - Verzenden van status en events via BLE
    - Testmodus genereren en beheren
    """
    def __init__(self):
        self.cfg = load_config()
        log("info", f"WaterModule initialized with config: {self.cfg}")
        # Align runtime log-level with config
        try:
            set_log_level(self.cfg.get("log_level", "info"))
        except Exception:
            pass
        
        # Initialize components
        self._init_pins()
        self._init_uart()
        if self.cfg["ble_enabled"] and bluetooth:
            self._init_ble()
        
        # State variables
        self.test_active = False
        self.test_data_active = False  # Separate flag for test data generation
        # Testmodus-opties (configureerbaar via config en BLE-commando's)
        self.test_pipeline = bool(self.cfg.get("test_pipeline", False))
        self.test_allow_outputs = bool(self.cfg.get("test_allow_outputs", False))
        self.test_start_time = 0
        self.test_data_id = 0  # Unique ID for each test session
        self.current_level = 50.0  # Real sensor level
        self.test_level = None     # Separate test level
        self.current_state = STATE_OK
        self.sensor_valid = False  # Whether we have valid sensor data
        self.ready = False
        self.last_sensor_time = 0
        self.boot_time = time.time()
        # Monotonic timers (ms) for reliable 1 Hz scheduling
        try:
            self._now_ms = time.ticks_ms
            self._diff_ms = time.ticks_diff
        except Exception:
            self._now_ms = lambda: int(time.time() * 1000)
            self._diff_ms = lambda a, b: a - b
        self._last_test_ble_ms = 0
        self._last_status_ms = 0
        self._last_sys_err_ms = 0
        self.test_pct = None
        self.seq = 0
        self.ema_level = None
        self._uart_buf = b""
        self._sensor_fail_count = 0
        self._sensor_fail_threshold = 3
        # Test injectie queue voor UART-bytes (simulatie van chunking)
        self._test_inject_queue = []
        # State hysteresis/debounce
        self._pending_state = self.current_state
        self._pending_since_ms = self._now_ms()
        self._last_committed_state = self.current_state

        # Optional hardware watchdog
        self._wdt = None
        if self.cfg.get("wdt_enabled", True):
            try:
                from machine import WDT
                self._wdt = WDT(timeout=int(self.cfg.get("wdt_timeout_ms", 8000)))
                log("info", "Hardware watchdog enabled")
            except Exception as _:
                self._wdt = None
        
    def _init_pins(self):
        """Initialiseer alle relevante GPIO-pinnen in een veilige uitgangsstaat.

        Let op: waarde 1 is 'safe' voor interlock/pump/heater.
        Pin-objecten voor kritieke uitgangen worden gecachet om overhead en
        mogelijke glitches te beperken.
        """
        try:
            # Cache critical output pins and set safe state (1)
            self._pin_interlock = None
            self._pin_pump = None
            self._pin_heater = None
            try:
                if self.cfg.get("interlock_pin") is not None:
                    self._pin_interlock = Pin(self.cfg["interlock_pin"], Pin.OUT)
                    self._pin_interlock.value(1)
                    log("info", f"Pin {self.cfg['interlock_pin']} (interlock_pin) initialized to safe")
            except Exception:
                self._pin_interlock = None
            try:
                if self.cfg.get("pump_ok_pin") is not None:
                    self._pin_pump = Pin(self.cfg["pump_ok_pin"], Pin.OUT)
                    self._pin_pump.value(1)
                    log("info", f"Pin {self.cfg['pump_ok_pin']} (pump_ok_pin) initialized to safe")
            except Exception:
                self._pin_pump = None
            try:
                if self.cfg.get("heater_ok_pin") is not None:
                    self._pin_heater = Pin(self.cfg["heater_ok_pin"], Pin.OUT)
                    self._pin_heater.value(1)
                    log("info", f"Pin {self.cfg['heater_ok_pin']} (heater_ok_pin) initialized to safe")
            except Exception:
                self._pin_heater = None

            # Initialize LED once for stable blinking
            self.led = None
            try:
                if self.cfg.get("led_pin"):
                    self.led = Pin(self.cfg["led_pin"], Pin.OUT)
                    self.led.value(0)
            except Exception:
                self.led = None
        except Exception as e:
            log("error", f"Pin initialization failed: {e}")
    
    def _init_uart(self):
        """Maak de UART-verbinding aan voor de afstandssensor.

        Bij falen blijft `self.uart` op `None` en wordt de module in FAULT gehouden.
        """
        try:
            self.uart = UART(self.cfg["uart_port"], 
                           baudrate=self.cfg["uart_baud"],
                           tx=self.cfg["uart_tx"], 
                           rx=self.cfg["uart_rx"])
            log("info", f"UART initialized on port {self.cfg['uart_port']}")
        except Exception as e:
            log("error", f"UART initialization failed: {e}")
            self.uart = None
    
    def _init_ble(self):
        """Initialiseer de eenvoudige BLE-service en start adverteren."""
        try:
            # Respecteer optionele BLE rate limit voor NOTIFY's (ble_send_interval_ms)
            self.ble = SimpleBLE(self.cfg["ble_name"], send_interval_ms=int(self.cfg.get("ble_send_interval_ms", 1000)))
            log("info", f"BLE initialized with name: {self.cfg['ble_name']}")
        except Exception as e:
            log("error", f"BLE initialization failed: {e}")
            self.ble = None
    
    def _check_ready(self):
        """Zet `ready=True` zodra de boot-grace-periode verstreken is.

        Bij overgang naar `ready=True` wordt meteen `_apply_fail_safe_outputs()`
        aangeroepen zodat de actuele (gegate) uitgangsstaten worden toegepast.
        """
        if not self.ready and (time.time() - self.boot_time) >= self.cfg["boot_grace_s"]:
            self.ready = True
            log("info", "System ready")
            # Apply outputs upon becoming ready (gated logic inside will decide)
            try:
                self._apply_fail_safe_outputs()
            except Exception:
                pass
    
    def _update_level_state(self):
        """Werk `ema_level`, `current_state` en fail-safe aansturing bij op basis van sensor.

        Retourneert het berekende percentage t.o.v. de kalibratie.
        Debounce is configureerbaar via `debounce_ms` en versnelt fail-safe zonder
        te veel jitter te introduceren.
        """
        # Apply EMA to current_level when valid
        if self.sensor_valid:
            alpha = float(self.cfg.get("ema_alpha", 0.25))
            if self.ema_level is None:
                self.ema_level = self.current_level
            else:
                self.ema_level = alpha * self.current_level + (1.0 - alpha) * self.ema_level
        level_for_state = self.ema_level if (self.sensor_valid and self.ema_level is not None) else self.current_level
        if self.cfg["cal_full_mm"] and self.cfg["cal_empty_mm"] and level_for_state is not None:
            full_mm = self.cfg["cal_full_mm"]
            empty_mm = self.cfg["cal_empty_mm"]
            if full_mm < empty_mm:
                pct = max(0, min(100, (empty_mm - level_for_state) / (empty_mm - full_mm) * 100))
            else:
                pct = max(0, min(100, (level_for_state - empty_mm) / (full_mm - empty_mm) * 100))
        else:
            pct = 50.0
        
        # Hysteresis and debounce
        hyst = float(self.cfg.get("hysteresis_pct", 4))
        desired = self._decide_state_with_hysteresis(pct, hyst)
        now_ms = self._now_ms()
        if desired != self._pending_state:
            self._pending_state = desired
            self._pending_since_ms = now_ms
        debounce_ms = int(self.cfg.get("debounce_ms", 200))
        if self._diff_ms(now_ms, self._pending_since_ms) >= debounce_ms and desired != self.current_state:
            old_state = self.current_state
            self.current_state = desired
            self._last_committed_state = desired
            log("info", f"State changed: {old_state} -> {self.current_state} (pct: {pct:.1f}%)")
            self._apply_fail_safe_outputs()
        
        return pct
    
    def _update_level_state_from_level(self, level):
        """Variant van `_update_level_state` voor een expliciet mm-niveau (b.v. testmodus).

        Tijdens testmodus wordt de toestandsmachine wel bijgewerkt ten behoeve
        van visualisatie, maar de uitgangen blijven via `_apply_fail_safe_outputs`
        geforceerd in veilige stand.
        """
        # If no valid sensor data, return FAULT state
        if not self.sensor_valid and not self.test_active:
            self.current_state = STATE_FAULT
            return 0.0  # 0% when in fault
        
        if self.cfg["cal_full_mm"] and self.cfg["cal_empty_mm"]:
            full_mm = self.cfg["cal_full_mm"]
            empty_mm = self.cfg["cal_empty_mm"]
            if full_mm < empty_mm:
                pct = max(0, min(100, (empty_mm - level) / (empty_mm - full_mm) * 100))
            else:
                pct = max(0, min(100, (level - empty_mm) / (full_mm - empty_mm) * 100))
        else:
            pct = 50.0
        
        # Apply hysteresis/ debounce using computed pct
        hyst = float(self.cfg.get("hysteresis_pct", 4))
        desired = self._decide_state_with_hysteresis(pct, hyst)
        now_ms = self._now_ms()
        if desired != self._pending_state:
            self._pending_state = desired
            self._pending_since_ms = now_ms
        debounce_ms = int(self.cfg.get("debounce_ms", 200))
        if self._diff_ms(now_ms, self._pending_since_ms) >= debounce_ms and desired != self.current_state:
            old_state = self.current_state
            self.current_state = desired
            self._last_committed_state = desired
            log("info", f"State changed: {old_state} -> {self.current_state} (pct: {pct:.1f}%, sensor_valid: {self.sensor_valid})")
            self._apply_fail_safe_outputs()
        
        return pct

    def _decide_state_with_hysteresis(self, pct, hyst):
        """Toestandsmachine met hysterese rond `low_pct` en `bottom_pct`."""
        if not self.sensor_valid and not self.test_active:
            return STATE_FAULT
        low = float(self.cfg.get("low_pct", 30))
        bottom = float(self.cfg.get("bottom_pct", 10))
        st = self.current_state
        # Compute entry/exit thresholds
        to_bottom = pct <= (bottom - hyst)
        to_low = pct <= (low - hyst)
        to_ok = pct >= (low + hyst)
        if st == STATE_BOTTOM:
            return STATE_BOTTOM if pct <= (bottom + hyst) else (STATE_LOW if pct <= (low - hyst) else STATE_OK)
        if st == STATE_LOW:
            if to_bottom:
                return STATE_BOTTOM
            return STATE_LOW if pct <= (low + hyst) else STATE_OK
        if st == STATE_OK:
            if to_bottom:
                return STATE_BOTTOM
            return STATE_LOW if to_low else STATE_OK
        return STATE_OK

    def _apply_fail_safe_outputs(self):
        """Zet interlock/pump/heater outputs afhankelijk van de toestand.

        Veiligheidsregels:
        - Testmodus: altijd geforceerd veilig (waarde 1) ongeacht toestand.
        - Voor `ready=True`: altijd veilig (boot-grace gating).
        - Bij ongeldige sensor/FAULT: veilige stand.
        - Anders: vrijgave afhankelijk van toestand en configuratie (conservatief
          bij `allow_pump_at_low=False`).
        """
        try:
            interlock_active = bool(self.cfg.get("interlock_active", True))
            allow_pump_at_low = bool(self.cfg.get("allow_pump_at_low", False))

            # During test mode: force safe unless explicitly allowed
            if self.test_active and not self.test_allow_outputs:
                try:
                    if self._pin_pump and bool(self.cfg.get("use_pump_ok", True)):
                        self._pin_pump.value(1)
                    if self._pin_heater and bool(self.cfg.get("use_heater_ok", True)):
                        self._pin_heater.value(1)
                    if self._pin_interlock and interlock_active:
                        self._pin_interlock.value(1)
                except Exception:
                    pass
                return

            # Before system is ready: keep everything safe
            if not self.ready:
                try:
                    if self._pin_pump and bool(self.cfg.get("use_pump_ok", True)):
                        self._pin_pump.value(1)
                    if self._pin_heater and bool(self.cfg.get("use_heater_ok", True)):
                        self._pin_heater.value(1)
                    if self._pin_interlock and interlock_active:
                        self._pin_interlock.value(1)
                except Exception:
                    pass
                return

            # Determine safe/ok based on current state and sensor validity
            ok_for_pump = self.sensor_valid and (self.current_state == STATE_OK or (self.current_state == STATE_LOW and allow_pump_at_low))
            ok_for_heater = self.sensor_valid and (self.current_state == STATE_OK)

            # Safe is value 1, ok is value 0
            try:
                if self._pin_pump and bool(self.cfg.get("use_pump_ok", True)):
                    self._pin_pump.value(0 if ok_for_pump else 1)
            except Exception:
                pass
            try:
                if self._pin_heater and bool(self.cfg.get("use_heater_ok", True)):
                    self._pin_heater.value(0 if ok_for_heater else 1)
            except Exception:
                pass
            try:
                if self._pin_interlock and interlock_active:
                    self._pin_interlock.value(1 if not ok_for_pump else 0)
            except Exception:
                pass
        except Exception as e:
            log("warn", f"Fail-safe apply error: {e}")
    
    def _generate_test_data(self, force_send=False):
        """Genereer en publiceer zaagtand-testdata voor het dashboard via BLE."""
        if not self.test_data_active:
            return
        
        elapsed = time.time() - self.test_start_time
        period = self.cfg["test_period_s"]
        if period <= 0:
            period = 20
        # Generate sawtooth percentage (100 -> 0 over 'period')
        frac = (elapsed % period) / period
        self.test_pct = max(0.0, min(100.0, 100.0 * (1.0 - frac)))
        # Map pct to a test_level within calibration range for display
        full_mm = self.cfg.get("cal_full_mm", self.cfg["min_mm"])
        empty_mm = self.cfg.get("cal_empty_mm", self.cfg["max_mm"])
        try:
            if full_mm < empty_mm:
                # 100% -> full_mm, 0% -> empty_mm
                self.test_level = full_mm + (empty_mm - full_mm) * (1.0 - self.test_pct / 100.0)
            else:
                self.test_level = empty_mm + (full_mm - empty_mm) * (self.test_pct / 100.0)
        except Exception:
            # Fallback to min/max range
            level_range = self.cfg["max_mm"] - self.cfg["min_mm"]
            self.test_level = self.cfg["min_mm"] + (1.0 - self.test_pct / 100.0) * level_range
        # Inject in pipeline of direct state (klassiek)
        if self.test_pipeline:
            try:
                # Wordt in _read_sensor() verwerkt via injectiequeue om UART-chunking te simuleren
                self._enqueue_test_uart_line(self.test_level)
            except Exception:
                pass
        else:
            # Derive state from pct (ignore sensor flags during classic test)
            if self.test_pct <= self.cfg["bottom_pct"]:
                self.current_state = STATE_BOTTOM
            elif self.test_pct <= self.cfg["low_pct"]:
                self.current_state = STATE_LOW
            else:
                self.current_state = STATE_OK
        
        # Limit BLE updates to max 1x per second for stability (unless forced)
        now_ms = self._now_ms()
            
        # Send test data via BLE - use same format as _send_status for consistency
        if self.ble and (force_send or (self._diff_ms(now_ms, self._last_test_ble_ms) >= 1000)):
            test_data = {
                "seq": self.seq,
                "ts_ms": int(time.time() * 1000),
                # Core status fields (same as _send_status)
                "state": self.current_state,
                "pct": self.test_pct,
                "ready": self.ready,
                "test_active": True,
                "current_level_mm": self.test_level,
                "last_sensor_time": self.last_sensor_time,
                "ema_mm": self.ema_level if self.sensor_valid else None,
                "obs_min": self.cfg["min_mm"],
                "obs_max": self.cfg["max_mm"],
                
                # Test specific fields
                "evt": "test",
                "test_data_id": self.test_data_id,
                "test_elapsed": elapsed,
                "test_period": period,
                
                # DEBUG fields for consistency
                "DEBUG_test_level": self.test_level,
                "DEBUG_current_level": self.current_level,
                "DEBUG_sensor_valid": self.sensor_valid,
                "DEBUG_test_data_active": self.test_data_active
            }
            try:
                payload = json.dumps(test_data)
                if force_send and hasattr(self.ble, 'notify_priority'):
                    self.ble.notify_priority(payload)
                else:
                    self.ble.notify(payload)
                self.seq = (self.seq + 1) & 0xFFFFFFFF
                log("info", f"Test data sent via BLE")
                self._last_test_ble_ms = now_ms
            except Exception as e:
                log("error", f"Failed to send test data: {e}")
        
        # Always log test data locally (even if not sent via BLE due to rate limiting)
        log("info", f"Test data: level={self.test_level:.1f}mm, pct={self.test_pct:.1f}%, state={self.current_state}")
    
    def _read_sensor(self):
        """Lees UART-buffer niet-blokkerend, parse mm-waarde en valideer met grenzen.

        Robuustheid:
        - UART-buffer wordt begrensd (`uart_buf_max`) om RAM-groei te voorkomen.
        - `sensor_valid=False` pas na meerdere opeenvolgende fouten om flapperen
          en onnodige fail-safe toggles te vermijden.
        - Timeout markeert sensor als ongeldig met throttled sys-event.
        """
        try:
            data_added = False
            # Testinjectie: simuleer uart.read() chunking
            if self.test_active and self.test_pipeline and self._test_inject_queue:
                try:
                    inj = self._test_inject_queue.pop(0)
                    if inj:
                        self._uart_buf += inj
                        data_added = True
                except Exception:
                    pass
            # Echte UART
            if self.uart and self.uart.any():
                try:
                    chunk = self.uart.read()
                except Exception:
                    chunk = None
                if chunk:
                    self._uart_buf += chunk
                    data_added = True
            # Cap buffer en verwerk complete regels
            if data_added:
                try:
                    max_buf = int(self.cfg.get("uart_buf_max", 256))
                except Exception:
                    max_buf = 256
                if len(self._uart_buf) > max_buf:
                    self._uart_buf = self._uart_buf[-max_buf:]
                while b"\n" in self._uart_buf:
                    line, _, rest = self._uart_buf.partition(b"\n")
                    self._uart_buf = rest
                    self._process_uart_text_line(line)
            else:
                # No data available; check timeout to flag sensor fault
                try:
                    timeout_ms = int(self.cfg.get("timeout_ms", 1200))
                except Exception:
                    timeout_ms = 1200
                # If we've never had a reading, use boot-time as reference
                last_s = self.last_sensor_time or self.boot_time
                if ((time.time() - last_s) * 1000) >= timeout_ms:
                    if self.sensor_valid:
                        log("warn", "Sensor timeout - marking sensor_invalid")
                    self.sensor_valid = False
                    # Emit a throttled sys event so the dashboard can show a hint
                    self._emit_sys_event_throttled("sensor timeout", err="no_data")
        except Exception as e:
            log("error", f"UART read failed: {e}")
            self.sensor_valid = False

    def _process_uart_text_line(self, raw_line):
        """Parse één UART-regel meting in mm en werk sensortoestand bij.

        - Negeer lege/corrupte regels of commentaar (#)
        - Clamp naar plausibel bereik [min_mm, max_mm]
        - Houd eenvoudige fail-counter bij om korte glitches te negeren
        """
        try:
            if isinstance(raw_line, (bytes, bytearray)):
                s = raw_line.decode('utf-8', 'ignore')
            else:
                s = str(raw_line)
            s = s.replace('\r', '').strip()
            if not s or s.startswith('#'):
                return
            mm = float(s)
        except Exception:
            return

        try:
            mn = float(self.cfg.get("min_mm", 0))
            mx = float(self.cfg.get("max_mm", 1000))
        except Exception:
            mn, mx = 0.0, 1000.0

        # Buiten plausibel venster met marge → fout tellen
        if mm < (mn - 10) or mm > (mx + 10):
            try:
                self._sensor_fail_count += 1
                if self._sensor_fail_count >= self._sensor_fail_threshold:
                    self.sensor_valid = False
            except Exception:
                self.sensor_valid = False
            return

        if mm < mn:
            mm = mn
        if mm > mx:
            mm = mx

        self.current_level = mm
        self.sensor_valid = True
        self.last_sensor_time = time.time()
        self._sensor_fail_count = 0

    def _enqueue_test_uart_line(self, level_mm):
        """Bouw een UART-regel voor `level_mm` met optionele ruis/corruptie en splits in chunks.

        Chunks worden in `_test_inject_queue` geplaatst en bij de volgende `_read_sensor()` verwerkt,
        waardoor framing/chunking realistisch wordt gesimuleerd.
        """
        try:
            # Dropout: skip hele sample
            if (self._rand() < float(self.cfg.get("test_dropout_prob", 0.0))):
                return
            # Noise
            noise_amp = float(self.cfg.get("test_noise_mm", 0.0))
            if noise_amp > 0.0:
                level_mm = float(level_mm) + self._uniform_noise(-noise_amp, noise_amp)
            # Outlier
            if (self._rand() < float(self.cfg.get("test_outlier_prob", 0.0))):
                if self._rand() < 0.5:
                    level_mm = float(self.cfg["min_mm"]) - 5.0
                else:
                    level_mm = float(self.cfg["max_mm"]) + 5.0
            # Build line
            line = ("%0.1f" % float(level_mm))
            if (self._rand() < float(self.cfg.get("test_corrupt_prob", 0.0))):
                line = "#" + line + "xx"
            data = (line + "\n").encode()
            # Chunking
            min_c = int(self.cfg.get("test_uart_chunk_min", 4))
            max_c = int(self.cfg.get("test_uart_chunk_max", 12))
            i = 0
            chunks = []
            while i < len(data):
                n = min_c if max_c <= min_c else self._rand_int(min_c, max_c)
                if n <= 0:
                    n = min_c
                chunks.append(data[i:i+n])
                i += n
            # Jitter: soms een iteratie overslaan
            if (self._rand() < float(self.cfg.get("test_jitter_skip_prob", 0.0))):
                return
            for ch in chunks:
                self._test_inject_queue.append(ch)
        except Exception:
            pass

    def _emit_sys_event_throttled(self, msg, err=None):
        """Stuur een systeembericht via BLE met minimaal 2s interval om spam te voorkomen."""
        try:
            now_ms = self._now_ms()
            if self.ble and self._diff_ms(now_ms, self._last_sys_err_ms) >= 2000:
                payload = {"evt": "sys", "msg": msg}
                if err:
                    payload["err"] = err
                payload["sensor_valid"] = self.sensor_valid
                try:
                    self.ble.notify(json.dumps(payload))
                except Exception:
                    pass
                self._last_sys_err_ms = now_ms
        except Exception:
            pass
    
    def _send_status(self):
        """Verzend een geconsolideerde statuspayload via BLE (max 1×/s)."""
        if not self.ble:
            return
        
        try:
            # DETAILED TRACING - Log EVERYTHING
            log("info", f"[TRACE] _send_status called")
            log("info", f"[TRACE] test_active={self.test_active}, test_data_active={self.test_data_active}")
            log("info", f"[TRACE] current_level={self.current_level}, test_level={self.test_level}")
            log("info", f"[TRACE] sensor_valid={self.sensor_valid}, current_state={self.current_state}")
            
            # Choose display and compute pct. Use state machine consistently:
            # - Classic test: compute pct from synthetic level for UI only
            # - Normal/pipeline: update state from real sensor path
            if self.test_active and not self.test_pipeline:
                display_level = self.test_level
                is_valid = True
                log("info", f"[TRACE] Using TEST mode (classic): display_level={display_level}")
                pct = self._update_level_state_from_level(display_level)
            else:
                display_level = self.current_level if self.sensor_valid else None
                is_valid = self.sensor_valid
                log("info", f"[TRACE] Using NORMAL/PIPE mode: display_level={display_level}, is_valid={is_valid}")
                pct = self._update_level_state()
            log("info", f"[TRACE] Calculated pct={pct}, final state={self.current_state}")
            
            status_data = {
                "seq": self.seq,
                "ts_ms": int(time.time() * 1000),
                "state": self.current_state,
                "pct": pct,
                "ready": self.ready,
                "test_active": self.test_active,
                "current_level_mm": display_level,
                "last_sensor_time": self.last_sensor_time,
                # Add fields that the dashboard expects for the gauge
                "ema_mm": (self.ema_level if is_valid else None),  # None if invalid
                "obs_min": self.cfg["min_mm"],
                "obs_max": self.cfg["max_mm"],
                # DEBUG FIELDS
                "DEBUG_test_level": self.test_level,
                "DEBUG_current_level": self.current_level,
                "DEBUG_sensor_valid": self.sensor_valid,
                "DEBUG_test_data_active": self.test_data_active
            }
            self.ble.notify(json.dumps(status_data))
            self.seq = (self.seq + 1) & 0xFFFFFFFF
            log("info", f"[TRACE] Status SENT: {status_data}")
        except Exception as e:
            log("error", f"Failed to send status: {e}")
    
    def start_test(self, pipeline=None, allow_outputs=None):
        """Activeer testmodus met optionele pipeline/outputs.

        - pipeline=True: voer synthetische metingen via de normale parser in
          (UART-pad, sensor_valid, EMA en outputs worden normaal geëvalueerd).
        - allow_outputs=True: laat outputs in test vrijgeven alsof het normaal is.
        """
        self.test_active = True
        self.test_data_active = True  # Enable test data generation
        if pipeline is not None:
            self.test_pipeline = bool(pipeline)
        if allow_outputs is not None:
            self.test_allow_outputs = bool(allow_outputs)
        self.test_start_time = time.time()
        self.test_data_id += 1  # Increment test ID for new session
        # Initialize test level to current real level
        self.test_level = self.current_level
        log("info", f"Test mode started, ID: {self.test_data_id}, initial test level: {self.test_level:.1f}mm")
        
        # Reset test BLE timer so we can send immediately
        self._last_test_ble_ms = 0
        
        # Send immediate small start event with priority if available
        if self.ble:
            try:
                test_start_data = {
                    "evt": "test",
                    "test_active": True,
                    "test_data_id": self.test_data_id
                }
                payload = json.dumps(test_start_data)
                if hasattr(self.ble, 'notify_priority'):
                    self.ble.notify_priority(payload)
                else:
                    self.ble.notify(payload)
                log("info", "Test start notification sent via BLE")
            except Exception as e:
                log("error", f"Failed to send test start: {e}")
        
        # Send first test data immediately to kick the dashboard
        try:
            self._generate_test_data(force_send=True)
        except Exception as e:
            log("error", f"Failed to send initial test data: {e}")
    
    def stop_test(self):
        """Deactiveer testmodus en stuur één geconsolideerde stopnotificatie."""
        log("info", f"[TRACE] stop_test() CALLED")
        log("info", f"[TRACE] BEFORE stop: test_active={self.test_active}, current_level={self.current_level}, sensor_valid={self.sensor_valid}")
        
        self.test_active = False
        self.test_data_active = False  # Stop test data generation immediately
        self.test_level = None  # Clear test level
        # Reset test options to conservative defaults from config
        self.test_pipeline = bool(self.cfg.get("test_pipeline", False))
        self.test_allow_outputs = bool(self.cfg.get("test_allow_outputs", False))
        log("info", f"[TRACE] FLAGS SET: test_active={self.test_active}, test_data_active={self.test_data_active}, test_level={self.test_level}")
        
        # Force a sensor read to get current real level
        if self.uart:
            log("info", f"[TRACE] Attempting sensor read...")
            self._read_sensor()
            log("info", f"[TRACE] After sensor read: current_level={self.current_level}, sensor_valid={self.sensor_valid}")
        
        # If no valid sensor data, set to FAULT state
        if not self.sensor_valid:
            log("info", f"[TRACE] No valid sensor - setting current_level to 0.0")
            self.current_level = 0.0  # Invalid level
            log("info", f"[TRACE] current_level set to: {self.current_level}")
        
        # Update state based on real sensor level
        log("info", f"[TRACE] Calling _update_level_state_from_level with level={self.current_level}")
        pct = self._update_level_state_from_level(self.current_level)
        log("info", f"[TRACE] After state update: pct={pct}, current_state={self.current_state}")
        
        # Send SINGLE consolidated notification after test stop to prevent BLE overload
        if self.ble:
            try:
                # Consolidate all test stop information into ONE BLE notification
                consolidated_stop_data = {
                    # Status information (replaces _send_status call)
                    "state": self.current_state,
                    "pct": pct,
                    "ready": self.ready,
                    "test_active": False,
                    "current_level_mm": self.current_level if self.sensor_valid else None,
                    "last_sensor_time": self.last_sensor_time,
                    "ema_mm": self.ema_level if self.sensor_valid else None,
                    "obs_min": self.cfg["min_mm"],
                    "obs_max": self.cfg["max_mm"],
                    
                    # Test stop event information
                    "evt": "test_stopped",  # Special event type for dashboard
                    "msg": "Test mode stopped",
                    "test_data_active": False,  # Explicitly indicate test data is stopped
                    "test_data_id": self.test_data_id,  # Include test ID for reference
                    "final_test_level": self.test_level,  # Last test level for reference
                    "current_real_level": self.current_level if self.sensor_valid else None,
                    "current_pct": pct,
                    "current_state": self.current_state,
                    "sensor_valid": self.sensor_valid,
                    
                    # DEBUG fields
                    "DEBUG_test_level": self.test_level,
                    "DEBUG_current_level": self.current_level,
                    "DEBUG_sensor_valid": self.sensor_valid,
                    "DEBUG_test_data_active": self.test_data_active
                }
                
                log("info", f"[TRACE] Sending CONSOLIDATED test stop notification")
                self.ble.notify(json.dumps(consolidated_stop_data))
                log("info", f"[TRACE] stop_test() COMPLETED - final state: {self.current_state}, level: {self.current_level}")
            except Exception as e:
                log("error", f"Failed to send consolidated test stop notification: {e}")
    
    def run(self):
        """Hoofdlus: lees sensor/testdata, werk toestand bij, stuur periodieke status.

        Indien geconfigureerd, wordt een hardware watchdog gevoed om vastlopers
        te detecteren en te resetten.
        """
        log("info", "WaterModule starting main loop")
        
        try:
            while True:
                try:
                    self._check_ready()
                    
                    if self.uart:
                        self._read_sensor()
                    
                    if self.test_active:
                        self._generate_test_data()
                    else:
                        # Only update level state when NOT in test mode
                        # This prevents overwriting the correct state set in stop_test()
                        self._update_level_state()
                    
                    # No explicit flush with simple notify

                    # Send status periodically
                    # - Skip during classic test to avoid BLE conflicts
                    # - Send during pipeline test to verify full flow
                    now_ms = self._now_ms()
                    if ((not self.test_active) or self.test_pipeline) and (self._diff_ms(now_ms, self._last_status_ms) >= 1000):
                        log("info", f"[TRACE] Main loop sending status - test_active={self.test_active}")
                        self._send_status()
                        self._last_status_ms = now_ms
                    
                    # Watchdog: if test is active but no test packet in 1.5s, force one
                    if self.test_active and (self._diff_ms(now_ms, self._last_test_ble_ms) >= 1500):
                        self._generate_test_data(force_send=True)
                        self._last_test_ble_ms = now_ms
                    
                    # Blink LED using initialized pin
                    if getattr(self, 'led', None) is not None:
                        try:
                            self.led.value(0 if self.led.value() else 1)
                        except Exception:
                            pass
                    
                    # Periodic garbage collection to avoid fragmentation
                    try:
                        gc.collect()
                    except Exception:
                        pass
                    # Feed hardware watchdog if present
                    if self._wdt:
                        try:
                            self._wdt.feed()
                        except Exception:
                            pass
                except Exception as loop_err:
                    # Log and continue; never let the loop die
                    log("err", f"Loop error: {loop_err}")
                
                time.sleep(1.0 / self.cfg["sample_hz"])
                
        except KeyboardInterrupt:
            log("info", "Stopped by user")
        except Exception as e:
            log("error", f"Fatal error: {e}")
            self._set_pins_safe()
            raise
        finally:
            self._set_pins_safe()
            log("info", "Module stopped, pins set to safe")
    
    def _set_pins_safe(self):
        """Zet alle kritieke uitgangen terug naar de veilige stand (waarde 1)."""
        try:
            # Prefer cached pins; fallback to ad-hoc if needed
            try:
                if self._pin_interlock:
                    self._pin_interlock.value(1)
                    log("info", f"Pin {self.cfg['interlock_pin']} (interlock_pin) set to safe")
                else:
                    pin_num = self.cfg.get("interlock_pin")
                    if pin_num is not None:
                        Pin(pin_num, Pin.OUT).value(1)
                        log("info", f"Pin {pin_num} (interlock_pin) set to safe")
            except Exception:
                pass
            try:
                if self._pin_pump:
                    self._pin_pump.value(1)
                    log("info", f"Pin {self.cfg['pump_ok_pin']} (pump_ok_pin) set to safe")
                else:
                    pin_num = self.cfg.get("pump_ok_pin")
                    if pin_num is not None:
                        Pin(pin_num, Pin.OUT).value(1)
                        log("info", f"Pin {pin_num} (pump_ok_pin) set to safe")
            except Exception:
                pass
            try:
                if self._pin_heater:
                    self._pin_heater.value(1)
                    log("info", f"Pin {self.cfg['heater_ok_pin']} (heater_ok_pin) set to safe")
                else:
                    pin_num = self.cfg.get("heater_ok_pin")
                    if pin_num is not None:
                        Pin(pin_num, Pin.OUT).value(1)
                        log("info", f"Pin {pin_num} (heater_ok_pin) set to safe")
            except Exception:
                pass
        except Exception as e:
            log("error", f"Failed to set pins safe: {e}")

