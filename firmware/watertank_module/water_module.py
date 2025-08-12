"""WaterTank core module for ESP32 (MicroPython).

Core logic managing the water level sensor, filtering, BLE interface and
safety interlocks. Split out from the original monolithic main.py for
modularity and reuse.
"""

import ujson as json
import uasyncio as asyncio
import machine
import time
import sys
import os
from machine import UART, Pin, WDT
import math

try:
    import bluetooth
except ImportError:
    bluetooth = None  # BLE optional for early bring-up

from .dypa02yy import DYPA02YY
from .level_estimator import (
    LevelEstimator,
    STATE_OK,
    STATE_LOW,
    STATE_BOTTOM,
    STATE_FAULT,
)
from .simple_ble import SimpleBLE

# ---------------------------- Configuration ---------------------------------

DEFAULT_CONFIG = {
    # UART wiring (DYP-A02YY UART)
    "uart_port": 2,          # MicroPython UART ID used for the sensor (typically 1 or 2)
    "uart_rx": 16,           # GPIO number for UART RX (sensor TX)
    "uart_tx": 17,           # GPIO number for UART TX (sensor RX)
    "uart_baud": 9600,       # DYP-A02YY default baudrate

    # Sampling & filtering
    "sample_hz": 8,          # sensor sampling frequency (Hz)
    "window": 5,             # median filter window size (number of samples)
    "ema_alpha": 0.25,       # EMA smoothing factor (0..1); higher = more responsive

    # Plausibility window for the Domobar tank geometry
    "min_mm": 30,            # plausible minimum distance (sensor blind zone ~30 mm)
    "max_mm": 220,           # plausible maximum distance (tank height + margin)

    # Sensor timeout
    "timeout_ms": 1200,      # if no valid reading for this long → FAULT

    # Level policy (percent of tank fullness)
    "bottom_pct": 10,        # percent threshold: empty. Interlocks enforced.
    "low_pct": 30,           # percent threshold: low. Heater disabled.
    "hysteresis_pct": 4,     # percent hysteresis band to avoid rapid toggling

    # Interlocks (active-LOW: 0=energize/run, 1=safe)
    "interlock_active": True, # master interlock logic enabled/disabled
    "interlock_pin": 15,      # GPIO that gates all loads; 0=allow, 1=safe (active-LOW)
    "pump_ok_pin": 14,        # GPIO that permits the pump; 0=allow, 1=stop (active-LOW)
    "heater_ok_pin": 27,      # GPIO that permits the heater; 0=allow, 1=stop (active-LOW)
    "use_pump_ok": True,      # if False: ignore pump_ok pin (left safe/off)
    "use_heater_ok": True,    # if False: ignore heater_ok pin (left safe/off)

    # UI/UX
    "led_pin": 2,             # GPIO for status LED (set to None to disable)
    "ble_enabled": True,      # enable Nordic UART-like BLE service (WebBLE)
    "ble_name": "VBMDSCSWT", # BLE GAP/advertising device name

    # Calibration (starter anchors; overwrite via CAL FULL/EMPTY)
    "cal_auto_learn": True,  # auto-track observed min/max to backstop missing anchors
    "cal_empty_mm": 190.0,   # initial EMPTY anchor (mm) — replace via CAL EMPTY
    "cal_full_mm": 50.0,     # initial FULL anchor (mm) — replace via CAL FULL

    # Behavior toggle
    "allow_pump_at_low": True,  # if False: pump allowed only in OK (not in LOW)

    # Logging
    "log_level": "info",       # one of: "err", "warn", "info"

    # Storage & boot
    "persist_path": "config.json", # where config is persisted on the device filesystem
    "boot_grace_s": 3,              # seconds after boot before becoming ready

    # Test mode
    "test_period_s": 20,      # period (seconds) for one full synthetic sweep in TEST mode
}

LOG_LEVELS = {"err": 0, "warn": 1, "info": 2}
_LOG_LEVEL = LOG_LEVELS.get(DEFAULT_CONFIG.get("log_level", "info"), 2)

def set_log_level(level):
    global _LOG_LEVEL
    _LOG_LEVEL = LOG_LEVELS.get(level, 2)

def log(level, msg):
    if LOG_LEVELS.get(level, 2) <= _LOG_LEVEL:
        print(f"[{level.upper()}] {msg}")

# ------------------------------ Utilities -----------------------------------

def load_config():
    try:
        with open(DEFAULT_CONFIG["persist_path"], "r") as f:
            cfg = json.loads(f.read())
        merged = DEFAULT_CONFIG.copy()
        merged.update(cfg)
        return merged
    except Exception:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

def save_config(cfg):
    tmp_path = cfg["persist_path"] + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(json.dumps(cfg, indent=2))
        try:
            os.rename(tmp_path, cfg["persist_path"])
        except Exception as e:
            log("warn", f"Config rename failed: {e}")
    except Exception as e:
        log("err", f"Config save error: {e}")

# --------------------------- Main Controller --------------------------------

class WaterModule:
    def __init__(self):
        # Load and merge persisted configuration with defaults.
        # On first boot (no file), defaults are stored.
        self.cfg = load_config()
        set_log_level(self.cfg.get("log_level", "info"))
        # Helper om pins veilig te initialiseren; retourneert None bij ongeldige pin
        def _safe_pin(pin_no, description):
            if pin_no is None:
                return None
            try:
                return Pin(pin_no, Pin.OUT)
            except Exception as e:
                log("warn", f"invalid {description} pin {pin_no}: {e}")
                return None

        self.led = _safe_pin(self.cfg["led_pin"], "led") if self.cfg["led_pin"] is not None else None

        self.interlock = _safe_pin(self.cfg["interlock_pin"], "interlock") if self.cfg["interlock_active"] else None
        self.pump_ok = _safe_pin(self.cfg["pump_ok_pin"], "pump_ok") if self.cfg["use_pump_ok"] else None
        self.heater_ok = _safe_pin(self.cfg["heater_ok_pin"], "heater_ok") if self.cfg["use_heater_ok"] else None

        # Ensure a safe default (active-LOW → 1 = safe/off) at boot
        for pin in (self.interlock, self.pump_ok, self.heater_ok):
            if pin:
                pin.value(1)  # safe default

        # Sensor UART; DYP-A02YY runs at 9600-8N1
        self.uart = UART(self.cfg["uart_port"], baudrate=self.cfg["uart_baud"], tx=self.cfg["uart_tx"], rx=self.cfg["uart_rx"])
        self.sensor = DYPA02YY(self.uart)
        self.est = LevelEstimator(self.cfg)

        # Optional BLE service for WebBluetooth dashboards
        self.ble = None
        if self.cfg["ble_enabled"] and bluetooth is not None:
            self.ble = SimpleBLE(self.cfg["ble_name"])
            self.ble.on_command = self._on_ble_command

        # Watchdog to recover from stalls; fed in the sense loop
        self.wdt = WDT(timeout=2000)
        self._last_read_ms = time.ticks_ms()
        self._boot_t0 = time.ticks_ms()
        # Becomes True after a short grace period and first valid reading
        self._ready = False

        # Test mode state: synthetic sweep replaces sensor input when enabled
        self.test_active = False
        self._test_t0 = None

    # BLE commands
    def _on_ble_command(self, cmd):
        cmd = cmd.strip().upper()
        # Lightweight command parser. Commands are intentionally simple.
        if cmd == "INFO?" and self.ble:
            info = {
                "state": self.est.state,
                "pct": self.est.last_pct,
                "cal_empty_mm": self.cfg["cal_empty_mm"],
                "cal_full_mm": self.cfg["cal_full_mm"],
                "obs_min": self.est.obs_min,
                "obs_max": self.est.obs_max,
            }
            self.ble.notify(json.dumps(info))
        elif cmd == "CFG?" and self.ble:
            keys = [
                "uart_port","uart_rx","uart_tx","sample_hz","bottom_pct","low_pct","hysteresis_pct",
                "interlock_active","use_pump_ok","use_heater_ok","min_mm","max_mm","timeout_ms",
                "allow_pump_at_low",
                # Include BLE fields so clients can verify/reset device identity
                "ble_enabled","ble_name"
            ]
            slim = {k:self.cfg.get(k) for k in keys}
            try:
                # Log a SYS marker to make debugging easier on the dashboard
                self.ble.notify(json.dumps({"evt":"sys","msg":"cfg_sent","num_keys": len(slim)}))
            except Exception:
                pass
            self.ble.notify(json.dumps(slim))
        elif cmd == "CAL EMPTY":
            v = self.est.ema
            if (v is not None) and math.isfinite(v) and (self.cfg["min_mm"] <= v <= self.cfg["max_mm"]):
                self.cfg["cal_empty_mm"] = float(v)
                save_config(self.cfg)
                if self.ble:
                    self.ble.notify("CAL EMPTY OK")
            else:
                if self.ble:
                    self.ble.notify("CAL REJECTED")
        elif cmd == "CAL FULL":
            v = self.est.ema
            if (v is not None) and math.isfinite(v) and (self.cfg["min_mm"] <= v <= self.cfg["max_mm"]):
                self.cfg["cal_full_mm"] = float(v)
                save_config(self.cfg)
                if self.ble:
                    self.ble.notify("CAL FULL OK")
            else:
                if self.ble:
                    self.ble.notify("CAL REJECTED")
        elif cmd == "TEST START":
            self.test_active = True
            self._test_t0 = time.ticks_ms()
            # For safety, consider system ready but keep outputs safe via _apply_outputs
            self._ready = True
            if self.ble:
                self.ble.notify(json.dumps({"evt":"test","msg":"started"}))
        elif cmd == "TEST STOP":
            self.test_active = False
            if self.ble:
                self.ble.notify(json.dumps({"evt":"test","msg":"stopped"}))
        elif cmd == "TEST?":
            if self.ble:
                self.ble.notify(json.dumps({"evt":"test","active": self.test_active}))
        elif cmd == "CAL CLEAR":
            self.cfg["cal_empty_mm"] = None
            self.cfg["cal_full_mm"] = None
            save_config(self.cfg)
            if self.ble: self.ble.notify("CAL CLEARED")
        elif cmd == "CFG RESET":
            # Restore defaults and persist. Running peripherals keep current init.
            self.cfg = DEFAULT_CONFIG.copy()
            save_config(self.cfg)
            if self.ble:
                try:
                    self.ble.notify(json.dumps({"evt":"sys","msg":"cfg_reset_ok"}))
                except Exception:
                    pass
        else:
            if self.ble: self.ble.notify("ERR CMD")

    # Output policy
    def _apply_outputs(self, state):
        # Active-LOW logic: 0=allow/run, 1=safe-stop
        allow_pump   = (state == STATE_OK) or (self.cfg.get("allow_pump_at_low", True) and state == STATE_LOW)
        allow_heater = (state == STATE_OK)
        # heater off already at LOW
        # Master interlock by state policy:
        #  - ON for OK and LOW (so pump may run at LOW if enabled)
        #  - OFF for BOTTOM and FAULT
        allow_master = (state in (STATE_OK, STATE_LOW))

        # In test mode: never energize outputs
        if self.test_active:
            allow_pump = False
            allow_heater = False
            allow_master = False

        if not self._ready:
            allow_pump = False
            allow_heater = False
            allow_master = False

        if self.interlock:
            self.interlock.value(0 if allow_master else 1)
        if self.pump_ok:
            self.pump_ok.value(0 if allow_pump else 1)
        if self.heater_ok:
            self.heater_ok.value(0 if allow_heater else 1)

    # Heartbeat
    async def _heartbeat(self):
        """LED heartbeat pattern encoding the current state.

        OK: short blink every second
        LOW: two quick blinks
        BOTTOM: three quick blinks
        FAULT/not-ready: long on, short off
        """
        while True:
            if self.led:
                st = self.est.state
                if st == STATE_OK:
                    self.led.value(1); await asyncio.sleep_ms(60)
                    self.led.value(0); await asyncio.sleep_ms(940)
                elif st == STATE_LOW:
                    for _ in range(2):
                        self.led.value(1); await asyncio.sleep_ms(80)
                        self.led.value(0); await asyncio.sleep_ms(120)
                    await asyncio.sleep_ms(700)
                elif st == STATE_BOTTOM:
                    for _ in range(3):
                        self.led.value(1); await asyncio.sleep_ms(80)
                        self.led.value(0); await asyncio.sleep_ms(120)
                    await asyncio.sleep_ms(500)
                else:
                    self.led.value(1); await asyncio.sleep_ms(800)
                    self.led.value(0); await asyncio.sleep_ms(200)
            else:
                await asyncio.sleep(1)

    # Sensor loop
    async def _sense_loop(self):
        """Main sensor loop.

        - Feeds the watchdog
        - Reads sensor or generates test values
        - Updates filtering and state
        - Applies safety outputs
        """
        period = max(0.02, 1.0 / float(self.cfg["sample_hz"]))
        last_valid_ms = time.ticks_ms()
        while True:
            try:
                self.wdt.feed()
                # Choose source: real sensor or test generator
                if self.test_active:
                    # Generate a smooth sawtooth between full and empty calibration anchors
                    now = time.ticks_ms()
                    if self._test_t0 is None:
                        self._test_t0 = now
                    period_s = self.cfg.get("test_period_s", 20)
                    try:
                        period_s = float(period_s)
                    except Exception:
                        period_s = 20.0
                    if period_s < 1.0:
                        period_s = 1.0  # minimum 1s per full cycle half
                    period_ms = int(period_s * 1000)
                    if period_ms <= 0:
                        period_ms = 20000
                    t = time.ticks_diff(now, self._test_t0)
                    if t < 0:
                        t = 0
                    t %= period_ms
                    ratio = t / float(period_ms)  # 0..1
                    full_mm = self.cfg["cal_full_mm"] if self.cfg["cal_full_mm"] is not None else self.cfg["min_mm"]
                    empty_mm = self.cfg["cal_empty_mm"] if self.cfg["cal_empty_mm"] is not None else self.cfg["max_mm"]
                    # Ensure numeric
                    try:
                        full_mm = float(full_mm)
                        empty_mm = float(empty_mm)
                    except Exception:
                        full_mm = float(self.cfg["min_mm"])
                        empty_mm = float(self.cfg["max_mm"])
                    # Sweep down then up across two halves of the period
                    if ratio < 0.5:
                        r = ratio / 0.5  # 0..1 downwards
                        mm = int(full_mm + r * (empty_mm - full_mm))
                    else:
                        r = (ratio - 0.5) / 0.5  # 0..1 upwards
                        mm = int(empty_mm + r * (full_mm - empty_mm))
                else:
                    mm = self.sensor.read_mm()

                now = time.ticks_ms()

                if mm is not None:
                    self._last_read_ms = now
                    last_valid_ms = now
                    _, pct = self.est.ingest_mm(mm)
                    new_state = self.est.decide_state() if pct is not None else STATE_FAULT
                else:
                    if time.ticks_diff(now, last_valid_ms) > self.cfg["timeout_ms"]:
                        new_state = STATE_FAULT
                    else:
                        new_state = self.est.state

                if (not self._ready) and (time.ticks_diff(now, self._boot_t0) > self.cfg["boot_grace_s"] * 1000) and (self.est.last_pct is not None):
                    self._ready = True

                if new_state != self.est.state:
                    self.est.state = new_state
                    if self.ble:
                        self.ble.notify(json.dumps({"evt":"state", "state":new_state, "pct":self.est.last_pct}))
                self._apply_outputs(self.est.state)
            except Exception as e:
                # Never let the loop die silently; surface minimal info over BLE
                try:
                    if self.ble:
                        self.ble.notify(json.dumps({"evt":"err","where":"sense","msg":str(e)}))
                except Exception:
                    pass
            # Use ms sleep for MicroPython reliability
            await asyncio.sleep_ms(int(period * 1000))

    # Periodic BLE push
    async def _ble_status(self):
        """Push a compact JSON status snapshot every ~2s over BLE."""
        while True:
            if self.ble:
                msg = {
                    "state": self.est.state,
                    "pct": self.est.last_pct,
                    "ema_mm": self.est.ema,
                    "obs_min": self.est.obs_min,
                    "obs_max": self.est.obs_max,
                    "ready": self._ready,
                    "test_active": self.test_active
                }
                self.ble.notify(json.dumps(msg))
            await asyncio.sleep_ms(2000)

    def run(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self._heartbeat())
        loop.create_task(self._sense_loop())
        if self.ble:
            loop.create_task(self._ble_status())
        loop.run_forever()

# ------------------------------- Boot ---------------------------------------

def main():
    mod = WaterModule()
    log("info", f"WaterModule starting with config: {mod.cfg}")
    try:
        mod.run()
    except KeyboardInterrupt:
        log("info", "Stopped")
    except Exception as e:
        log("err", f"Fatal: {e}")
        for pin_no in ("interlock_pin","pump_ok_pin","heater_ok_pin"):
            try:
                p = Pin(DEFAULT_CONFIG[pin_no], Pin.OUT)
                p.value(1)  # safe
            except Exception:
                pass
        raise

