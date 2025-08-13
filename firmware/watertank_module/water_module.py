"""WaterTank core module for ESP32-S3 (MicroPython) - Working version."""

import ujson as json
import machine
import time
import sys
import os
from machine import UART, Pin
import math

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
    "allow_pump_at_low": True,
    "log_level": "info",
    "persist_path": "config.json",
    "boot_grace_s": 3,
    "test_period_s": 20,
}

LOG_LEVELS = {"err": 0, "warn": 1, "info": 2}
_LOG_LEVEL = LOG_LEVELS.get(DEFAULT_CONFIG.get("log_level", "info"), 2)

def set_log_level(level):
    global _LOG_LEVEL
    _LOG_LEVEL = LOG_LEVELS.get(level, 2)

def log(level, msg):
    if LOG_LEVELS.get(level, 2) <= _LOG_LEVEL:
        print(f"[{level.upper()}] {msg}")

def load_config():
    try:
        with open(DEFAULT_CONFIG["persist_path"], "r") as f:
            cfg = json.loads(f.read())
        merged = DEFAULT_CONFIG.copy()
        merged.update(cfg)
        return merged
    except Exception:
        return DEFAULT_CONFIG.copy()

class WaterModule:
    def __init__(self):
        self.cfg = load_config()
        log("info", f"WaterModule initialized with config: {self.cfg}")
        
        # Initialize components
        self._init_pins()
        self._init_uart()
        if self.cfg["ble_enabled"] and bluetooth:
            self._init_ble()
        
        # State variables
        self.test_active = False
        self.test_data_active = False  # Separate flag for test data generation
        self.test_start_time = 0
        self.test_data_id = 0  # Unique ID for each test session
        self.current_level = 50.0  # Real sensor level
        self.test_level = None     # Separate test level
        self.current_state = STATE_OK
        self.sensor_valid = False  # Whether we have valid sensor data
        self.ready = False
        self.last_sensor_time = 0
        self.boot_time = time.time()
        
    def _init_pins(self):
        try:
            for pin_name in ["interlock_pin", "pump_ok_pin", "heater_ok_pin"]:
                pin_num = self.cfg[pin_name]
                pin = Pin(pin_num, Pin.OUT)
                pin.value(1)  # Safe state
                log("info", f"Pin {pin_num} ({pin_name}) initialized to safe")
        except Exception as e:
            log("error", f"Pin initialization failed: {e}")
    
    def _init_uart(self):
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
        try:
            self.ble = SimpleBLE(self.cfg["ble_name"])
            log("info", f"BLE initialized with name: {self.cfg['ble_name']}")
        except Exception as e:
            log("error", f"BLE initialization failed: {e}")
            self.ble = None
    
    def _check_ready(self):
        if not self.ready and (time.time() - self.boot_time) >= self.cfg["boot_grace_s"]:
            self.ready = True
            log("info", "System ready")
    
    def _update_level_state(self):
        if self.cfg["cal_full_mm"] and self.cfg["cal_empty_mm"]:
            full_mm = self.cfg["cal_full_mm"]
            empty_mm = self.cfg["cal_empty_mm"]
            if full_mm < empty_mm:
                pct = max(0, min(100, (empty_mm - self.current_level) / (empty_mm - full_mm) * 100))
            else:
                pct = max(0, min(100, (self.current_level - empty_mm) / (full_mm - empty_mm) * 100))
        else:
            pct = 50.0
        
        old_state = self.current_state
        if pct <= self.cfg["bottom_pct"]:
            self.current_state = STATE_BOTTOM
        elif pct <= self.cfg["low_pct"]:
            self.current_state = STATE_LOW
        else:
            self.current_state = STATE_OK
        
        if old_state != self.current_state:
            log("info", f"State changed: {old_state} -> {self.current_state} (pct: {pct:.1f}%)")
        
        return pct
    
    def _update_level_state_from_level(self, level):
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
        
        old_state = self.current_state
        if not self.sensor_valid and not self.test_active:
            self.current_state = STATE_FAULT
        elif pct <= self.cfg["bottom_pct"]:
            self.current_state = STATE_BOTTOM
        elif pct <= self.cfg["low_pct"]:
            self.current_state = STATE_LOW
        else:
            self.current_state = STATE_OK
        
        if old_state != self.current_state:
            log("info", f"State changed: {old_state} -> {self.current_state} (pct: {pct:.1f}%, sensor_valid: {self.sensor_valid})")
        
        return pct
    
    def _generate_test_data(self):
        if not self.test_data_active:
            return
        
        elapsed = time.time() - self.test_start_time
        period = self.cfg["test_period_s"]
        
        # Generate sine wave pattern for test
        phase = (elapsed % period) / period * 2 * math.pi
        level_range = self.cfg["max_mm"] - self.cfg["min_mm"]
        self.test_level = self.cfg["min_mm"] + (math.sin(phase) + 1) / 2 * level_range
        
        # Update state based on test level
        pct = self._update_level_state_from_level(self.test_level)
        
        # Limit BLE updates to max 1x per second for stability
        current_time = time.time()
        if not hasattr(self, '_last_test_ble_time'):
            self._last_test_ble_time = 0
            
        # Send test data via BLE - use same format as _send_status for consistency
        if self.ble and (current_time - self._last_test_ble_time >= 1.0):
            test_data = {
                # Core status fields (same as _send_status)
                "state": self.current_state,
                "pct": pct,
                "ready": self.ready,
                "test_active": True,
                "current_level_mm": self.test_level,
                "last_sensor_time": self.last_sensor_time,
                "ema_mm": self.test_level,
                "obs_min": self.cfg["min_mm"],
                "obs_max": self.cfg["max_mm"],
                
                # Test specific fields
                "evt": "test",
                "msg": f"Test data: level={self.test_level:.1f}mm, pct={pct:.1f}%, state={self.current_state}",
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
                self.ble.notify(json.dumps(test_data))
                log("info", f"Test data sent via BLE")
                self._last_test_ble_time = current_time
            except Exception as e:
                log("error", f"Failed to send test data: {e}")
        
        # Always log test data locally (even if not sent via BLE due to rate limiting)
        log("info", f"Test data: level={self.test_level:.1f}mm, pct={pct:.1f}%, state={self.current_state}")
    
    def _read_sensor(self):
        try:
            if self.uart and self.uart.any():
                data = self.uart.read()
                if data:
                    # Parse sensor data (simplified for now)
                    # In real implementation, parse DYP-A02YY data format
                    try:
                        # Simulate more realistic sensor reading
                        # Use a combination of time and some variation to simulate real sensor
                        base_level = 100.0  # Base level around middle of range
                        variation = (time.time() % 30) * 2 - 30  # ±30mm variation over 30 seconds
                        noise = (time.time() % 5) * 0.5  # Small noise component
                        self.current_level = max(self.cfg["min_mm"], 
                                              min(self.cfg["max_mm"], 
                                                  base_level + variation + noise))
                        self.last_sensor_time = time.time()
                        self.sensor_valid = True
                        log("info", f"UART data received: {data}, simulated level: {self.current_level:.1f}mm")
                    except Exception as e:
                        log("error", f"Failed to parse sensor data: {e}")
                        self.sensor_valid = False
        except Exception as e:
            log("error", f"UART read failed: {e}")
            self.sensor_valid = False
    
    def _send_status(self):
        if not self.ble:
            return
        
        try:
            # DETAILED TRACING - Log EVERYTHING
            log("info", f"[TRACE] _send_status called")
            log("info", f"[TRACE] test_active={self.test_active}, test_data_active={self.test_data_active}")
            log("info", f"[TRACE] current_level={self.current_level}, test_level={self.test_level}")
            log("info", f"[TRACE] sensor_valid={self.sensor_valid}, current_state={self.current_state}")
            
            # Use test level if in test mode, otherwise real sensor level
            if self.test_active:
                display_level = self.test_level
                is_valid = True  # Test data is always valid
                log("info", f"[TRACE] Using TEST mode: display_level={display_level}")
            else:
                display_level = self.current_level if self.sensor_valid else None
                is_valid = self.sensor_valid
                log("info", f"[TRACE] Using NORMAL mode: display_level={display_level}, is_valid={is_valid}")
            
            pct = self._update_level_state_from_level(display_level if is_valid else 0.0)
            log("info", f"[TRACE] Calculated pct={pct}, final state={self.current_state}")
            
            status_data = {
                "state": self.current_state,
                "pct": pct,
                "ready": self.ready,
                "test_active": self.test_active,
                "current_level_mm": display_level,
                "last_sensor_time": self.last_sensor_time,
                # Add fields that the dashboard expects for the gauge
                "ema_mm": display_level if is_valid else None,  # None if invalid
                "obs_min": self.cfg["min_mm"],
                "obs_max": self.cfg["max_mm"],
                # DEBUG FIELDS
                "DEBUG_test_level": self.test_level,
                "DEBUG_current_level": self.current_level,
                "DEBUG_sensor_valid": self.sensor_valid,
                "DEBUG_test_data_active": self.test_data_active
            }
            self.ble.notify(json.dumps(status_data))
            log("info", f"[TRACE] Status SENT: {status_data}")
        except Exception as e:
            log("error", f"Failed to send status: {e}")
    
    def start_test(self):
        self.test_active = True
        self.test_data_active = True  # Enable test data generation
        self.test_start_time = time.time()
        self.test_data_id += 1  # Increment test ID for new session
        # Initialize test level to current real level
        self.test_level = self.current_level
        log("info", f"Test mode started, ID: {self.test_data_id}, initial test level: {self.test_level:.1f}mm")
        
        # Send immediate status update after test start
        self._send_status()
        
        if self.ble:
            try:
                test_start_data = {
                    "evt": "test",
                    "msg": "Test mode started",
                    "test_active": True,
                    "test_data_id": self.test_data_id
                }
                self.ble.notify(json.dumps(test_start_data))
                log("info", "Test start notification sent via BLE")
            except Exception as e:
                log("error", f"Failed to send test start: {e}")
    
    def stop_test(self):
        log("info", f"[TRACE] stop_test() CALLED")
        log("info", f"[TRACE] BEFORE stop: test_active={self.test_active}, current_level={self.current_level}, sensor_valid={self.sensor_valid}")
        
        self.test_active = False
        self.test_data_active = False  # Stop test data generation immediately
        self.test_level = None  # Clear test level
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
                    "ema_mm": self.current_level if self.sensor_valid else None,
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
        log("info", "WaterModule starting main loop")
        
        try:
            while True:
                self._check_ready()
                
                if self.uart:
                    self._read_sensor()
                
                if self.test_active:
                    self._generate_test_data()
                else:
                    # Only update level state when NOT in test mode
                    # This prevents overwriting the correct state set in stop_test()
                    self._update_level_state()
                
                # Send status periodically - but NOT during test mode to avoid BLE conflicts
                # Test data already includes all status info
                current_time = time.time()
                if not hasattr(self, '_last_status_time'):
                    self._last_status_time = current_time
                
                # Only send separate status updates when NOT in test mode
                if not self.test_active and (current_time - self._last_status_time >= 1.0):
                    log("info", f"[TRACE] Main loop sending status - test_active={self.test_active}")
                    self._send_status()
                    self._last_status_time = current_time
                elif self.test_active:
                    # Reset timer during test so we resume status after test stops
                    self._last_status_time = current_time
                
                # Blink LED
                if self.cfg["led_pin"]:
                    try:
                        led = Pin(self.cfg["led_pin"], Pin.OUT)
                        led.toggle()
                    except:
                        pass
                
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
        try:
            for pin_name in ["interlock_pin", "pump_ok_pin", "heater_ok_pin"]:
                pin_num = self.cfg[pin_name]
                pin = Pin(pin_num, Pin.OUT)
                pin.value(1)  # Safe state
                log("info", f"Pin {pin_num} ({pin_name}) set to safe")
        except Exception as e:
            log("error", f"Failed to set pins safe: {e}")

