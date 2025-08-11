# main.py  — WaterTank Core Control Module for ESP32-WROOM-32E (MicroPython)
# Domobar Standaard/Classic — tuned defaults for reservoir geometry + safety
#
# SAFETY NOTE — Interlock Wiring:
#  - Use relay or SSR outputs in an "energize-to-run" (fail-safe) configuration.
#  - All interlock pins in this code assume active-LOW logic (0=allow/run, 1=stop).
#  - Wire pump and heater safety interlocks so that a logic HIGH from the MCU will
#    de-energize the load via the relay/SSR.
#  - This ensures that any MCU fault, crash, or reboot will default to safe-off.
#
# Changelog (tuned):
# - Defaults matched to VBM Domobar reservoir (~196 mm height, ~1.3 L):
#   * min_mm=30 (sensor blind zone), max_mm=220 (height+margin)
#   * cal_full_mm=50, cal_empty_mm=190 (starter anchors — run CAL FULL/EMPTY on-site)
#   * low_pct=30, bottom_pct=10, hysteresis_pct=4 (earlier heater cut @LOW)
#   * sample_hz=8, timeout_ms=1200 (align with sensor ~10 Hz)
#   * window=5, ema_alpha=0.25 (reduce slosh chatter)
# - Safety policy: heater OFF at LOW; both OFF at BOTTOM. Pump at LOW configurable.
#
# FIRST-RUN CHECKLIST (on machine):
#  1) Connect over BLE (DomobarTank) → press INFO? to verify values update.
#  2) Fill tank completely → press CAL FULL.
#  3) Empty tank to minimum (suction still wet) → press CAL EMPTY.
#  4) Press CFG? to confirm cal_* stored; verify OK/LOW/BOTTOM transitions.
#

import ujson as json
import uasyncio as asyncio
import machine
import time
import sys
from machine import UART, Pin, WDT
import math

try:
    import bluetooth
except ImportError:
    bluetooth = None  # BLE optional for early bring-up

# ---------------------------- Configuration ---------------------------------

DEFAULT_CONFIG = {
    # UART wiring (DYP-A02YY UART)
    "uart_port": 2,
    "uart_rx": 16,
    "uart_tx": 17,
    "uart_baud": 9600,

    # Sampling & filtering
    "sample_hz": 8,          # tuned: smooth yet responsive
    "window": 5,             # median window size
    "ema_alpha": 0.25,       # EMA smoothing factor

    # Plausibility window for the Domobar tank geometry
    "min_mm": 30,            # below sensor blind zone; reject <30 mm
    "max_mm": 220,           # tank height (~196 mm) + mounting margin

    # Sensor timeout
    "timeout_ms": 1200,      # > 1 reading stall → fault

    # Level policy (percent of tank fullness)
    "bottom_pct": 10,        # hard stop (interlocks)
    "low_pct": 30,           # early warning + heater cut
    "hysteresis_pct": 4,     # wider hysteresis to prevent chatter

    # Interlocks (active-LOW: 0=energize/run, 1=safe)
    "interlock_active": True,
    "interlock_pin": 15,
    "pump_ok_pin": 14,
    "heater_ok_pin": 27,
    "use_pump_ok": True,
    "use_heater_ok": True,

    # UI/UX
    "led_pin": 2,
    "ble_enabled": True,
    "ble_name": "DomobarTank",

    # Calibration (starter anchors; overwrite via CAL FULL/EMPTY)
    "cal_auto_learn": True,
    "cal_empty_mm": 190.0,   # starter — run CAL EMPTY on the machine
    "cal_full_mm": 50.0,     # starter — run CAL FULL on the machine

    # Behavior toggle
    "allow_pump_at_low": True,  # if False: pump only when state==OK

    # Storage & boot
    "persist_path": "config.json",
    "boot_grace_s": 3,
}

STATE_OK = "OK"
STATE_LOW = "LOW"
STATE_BOTTOM = "BOTTOM"
STATE_FAULT = "FAULT"

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
    try:
        with open(cfg["persist_path"], "w") as f:
            f.write(json.dumps(cfg))
    except Exception as e:
        print("Config save error:", e)

def clamp(x, a, b):
    return a if x < a else (b if x > b else x)

# --------------------------- Sensor Driver ----------------------------------

class DYPA02YY:
    """
    Robust reader for DYP-A02YY UART ultrasonic range finder.
    Supports binary and ASCII variants via auto-detect.
    Returns distance in millimeters or None on failure.
    """
    def __init__(self, uart):
        self.uart = uart
        self.mode = None  # "bin" or "asc"
        self._last_detect_t = 0

    def _detect_mode(self, buf):
        if len(buf) >= 4 and buf[0] == 0xFF:
            mm = (buf[2] << 8) | buf[3]
            if 0 < mm < 10000:
                return "bin"
        for c in buf:
            if 48 <= c <= 57:
                return "asc"
        return None

    def read_mm(self):
        n = self.uart.any()
        if n <= 0:
            return None
        data = self.uart.read(min(32, n))
        if not data:
            return None

        now = time.ticks_ms()
        if not self.mode or time.ticks_diff(now, self._last_detect_t) > 2000:
            m = self._detect_mode(data)
            if m:
                self.mode = m
                self._last_detect_t = now

        if self.mode == "bin":
            for i in range(len(data) - 3):
                if data[i] == 0xFF:
                    mm = (data[i+2] << 8) | data[i+3]
                    if 0 < mm < 10000:
                        return mm
            return None
        else:
            try:
                s = data.decode(errors="ignore")
                num = None
                acc = ""
                for ch in s:
                    if ch.isdigit():
                        acc += ch
                    else:
                        if acc:
                            num = int(acc)
                            acc = ""
                if acc:
                    num = int(acc)
                if num and 0 < num < 10000:
                    return num
            except Exception:
                pass
            return None

# --------------------------- Filtering & Levels ------------------------------

class LevelEstimator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.window = []
        self.ema = None
        self.obs_min = None
        self.obs_max = None
        self.state = STATE_FAULT
        self.last_pct = None

    def _median(self, arr):
        a = sorted(arr)
        n = len(a)
        if n == 0:
            return None
        mid = n // 2
        return (a[mid] if n % 2 == 1 else (a[mid-1] + a[mid]) / 2)

    def ingest_mm(self, mm):
        if mm is None:
            return None, None
        if not (self.cfg["min_mm"] <= mm <= self.cfg["max_mm"]):
            return None, None

        self.window.append(mm)
        if len(self.window) > max(3, self.cfg["window"]):
            self.window.pop(0)
        med = self._median(self.window)
        if med is None:
            return None, None

        a = self.cfg["ema_alpha"]
        self.ema = med if self.ema is None else (a * med + (1 - a) * self.ema)

        if self.cfg["cal_auto_learn"]:
            if (self.obs_min is None) or (self.ema < self.obs_min):
                self.obs_min = self.ema
            if (self.obs_max is None) or (self.ema > self.obs_max):
                self.obs_max = self.ema

        empty_mm = self.cfg["cal_empty_mm"] if self.cfg["cal_empty_mm"] is not None else (self.obs_max or self.cfg["max_mm"])
        full_mm  = self.cfg["cal_full_mm"]  if self.cfg["cal_full_mm"]  is not None else (self.obs_min or self.cfg["min_mm"])
        span = max(5.0, float(empty_mm - full_mm))
        pct = 100.0 * (empty_mm - float(self.ema)) / span
        pct = clamp(pct, 0.0, 100.0)

        self.last_pct = pct
        return self.ema, pct

    def decide_state(self):
        if self.last_pct is None:
            return STATE_FAULT
        low = self.cfg["low_pct"]
        bottom = self.cfg["bottom_pct"]
        h = self.cfg["hysteresis_pct"]
        cur = self.state
        p = self.last_pct

        if cur == STATE_FAULT:
            if p <= bottom:
                return STATE_BOTTOM
            elif p <= low:
                return STATE_LOW
            else:
                return STATE_OK

        if cur == STATE_OK:
            if p <= (low - h):
                return STATE_LOW
            return STATE_OK

        if cur == STATE_LOW:
            if p <= (bottom - h):
                return STATE_BOTTOM
            elif p >= (low + h):
                return STATE_OK
            return STATE_LOW

        if cur == STATE_BOTTOM:
            if p >= (bottom + h + h):
                return STATE_LOW if p <= (low - h) else STATE_OK
            return STATE_BOTTOM

        return STATE_FAULT

# ------------------------------- BLE ----------------------------------------

class SimpleBLE:
    """
    Minimal BLE status/command service.
    - Service UUID: 6E400001-B5A3-F393-E0A9-E50E24DCCA9E (Nordic UART style)
    - RX char (write): 6E400002-... ; TX char (notify): 6E400003-...
    Commands:
      * INFO?
      * CAL EMPTY
      * CAL FULL
      * CAL CLEAR
      * CFG?
    """
    def __init__(self, name="DomobarTank"):
        self.name = name
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
        UART_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_NOTIFY)
        UART_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_WRITE)
        UART_SERVICE = (UART_UUID, (UART_TX, UART_RX))
        ((self.tx_handle, self.rx_handle),) = self.ble.gatts_register_services((UART_SERVICE,))
        self.connections = set()
        self.ble.gap_advertise(100_000, adv_data=self._adv_payload(name=name))

    def _adv_payload(self, name=None):
        payload = bytearray(b"")
        if name:
            name_bytes = name.encode()
            payload += bytearray((len(name_bytes) + 1, 0x09)) + name_bytes
        return bytes(payload)

    def _irq(self, event, data):
        if event == 1:  # connect
            conn_handle, _, _ = data
            self.connections.add(conn_handle)
        elif event == 2:  # disconnect
            conn_handle, _, _ = data
            self.connections.discard(conn_handle)
            self.ble.gap_advertise(100_000, adv_data=self._adv_payload(name=self.name))
        elif event == 3:  # write
            conn_handle, value_handle = data
            if value_handle == self.rx_handle:
                msg = self.ble.gatts_read(self.rx_handle)
                self.on_command(msg.decode().strip())

    def on_command(self, cmd):
        pass

    def notify(self, text):
        for c in self.connections:
            try:
                self.ble.gatts_notify(c, self.tx_handle, text if isinstance(text, bytes) else text.encode())
            except:
                pass

# --------------------------- Main Controller --------------------------------

class WaterModule:
    def __init__(self):
        self.cfg = load_config()
        self.led = Pin(self.cfg["led_pin"], Pin.OUT) if self.cfg["led_pin"] is not None else None

        self.interlock = Pin(self.cfg["interlock_pin"], Pin.OUT) if self.cfg["interlock_active"] else None
        self.pump_ok = Pin(self.cfg["pump_ok_pin"], Pin.OUT) if self.cfg["use_pump_ok"] else None
        self.heater_ok = Pin(self.cfg["heater_ok_pin"], Pin.OUT) if self.cfg["use_heater_ok"] else None

        for pin in (self.interlock, self.pump_ok, self.heater_ok):
            if pin:
                pin.value(1)  # safe default

        self.uart = UART(self.cfg["uart_port"], baudrate=self.cfg["uart_baud"], tx=self.cfg["uart_tx"], rx=self.cfg["uart_rx"])
        self.sensor = DYPA02YY(self.uart)
        self.est = LevelEstimator(self.cfg)

        self.ble = None
        if self.cfg["ble_enabled"] and bluetooth is not None:
            self.ble = SimpleBLE(self.cfg["ble_name"])
            self.ble.on_command = self._on_ble_command

        self.wdt = WDT(timeout=2000)
        self._last_read_ms = time.ticks_ms()
        self._boot_t0 = time.ticks_ms()
        self._ready = False

    # BLE commands
    def _on_ble_command(self, cmd):
        cmd = cmd.strip().upper()
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
                "allow_pump_at_low"
            ]
            slim = {k:self.cfg.get(k) for k in keys}
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
        elif cmd == "CAL CLEAR":
            self.cfg["cal_empty_mm"] = None
            self.cfg["cal_full_mm"] = None
            save_config(self.cfg)
            if self.ble: self.ble.notify("CAL CLEARED")
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
        period = max(0.02, 1.0 / float(self.cfg["sample_hz"]))
        last_valid_ms = time.ticks_ms()
        while True:
            self.wdt.feed()
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

            await asyncio.sleep(period)

    # Periodic BLE push
    async def _ble_status(self):
        while True:
            if self.ble:
                msg = {
                    "state": self.est.state,
                    "pct": self.est.last_pct,
                    "ema_mm": self.est.ema,
                    "obs_min": self.est.obs_min,
                    "obs_max": self.est.obs_max,
                    "ready": self._ready
                }
                self.ble.notify(json.dumps(msg))
            await asyncio.sleep(2)

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
    print("WaterModule starting with config:", mod.cfg)
    try:
        mod.run()
    except KeyboardInterrupt:
        print("Stopped")
    except Exception as e:
        print("Fatal:", e)
        for pin_no in ("interlock_pin","pump_ok_pin","heater_ok_pin"):
            try:
                p = Pin(DEFAULT_CONFIG[pin_no], Pin.OUT)
                p.value(1)  # safe
            except:
                pass
        raise

if __name__ == "__main__":
    main()



