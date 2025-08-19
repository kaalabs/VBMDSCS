"""Entrypoint voor de WaterModule op de ESP32‑WROOM‑32E.

Taken
-----
- Initialiseert de `WaterModule`
- Verbindt de BLE-commandohandler
- Start de hoofdlus

Tip voor lezers: bekijk `water_module.py` voor de kernlogica en BLE-events.
"""

from machine import Pin
from water_module import WaterModule, log, DEFAULT_CONFIG
import time
import ujson

# Global reference to the water module
water_module = None

def save_config():
    """Save current water module configuration to persistent storage."""
    global water_module
    if not water_module:
        return False
    
    try:
        with open(water_module.cfg.get("persist_path", "config.json"), "w") as f:
            # Only save non-default values to keep the file clean
            config_to_save = {}
            for key, value in water_module.cfg.items():
                if key in DEFAULT_CONFIG and DEFAULT_CONFIG[key] != value:
                    config_to_save[key] = value
                elif key not in DEFAULT_CONFIG:
                    config_to_save[key] = value
            
            f.write(ujson.dumps(config_to_save, indent=2))
        log("info", f"Configuration saved to {water_module.cfg.get('persist_path', 'config.json')}")
        return True
    except Exception as e:
        log("error", f"Failed to save config: {e}")
        return False

def handle_command(cmd):
    """Verwerk inkomende BLE-commando's.

    Ondersteunde commando's:
    - "TEST START": activeert klassieke testmodus (outputs geforceerd veilig)
    - "TEST START PIPE": start pipeline test (synthetische metingen via parser)
    - "TEST START PIPE OUT": pipeline test met vrijgave outputs (gevaarlijk; alleen testomgeving)
    - "TEST STOP": stopt testmodus
    - "TEST?": status van testmodus
    - "INFO?": JSON met actuele status voor het dashboard
    - "CFG?": JSON met essentiële configuratie
    - "CAL FULL": kalibreer huidige niveau als 'vol'
    - "CAL EMPTY": kalibreer huidige niveau als 'leeg'
    - "CAL CLEAR": wis kalibratie-instellingen
    - "CFG RESET": herstel configuratie naar standaardwaarden
    """
    global water_module
    if not water_module:
        return "Water module not initialized"
    
    cmd = cmd.strip().upper()
    log("info", f"Received command: {cmd}")
    
    if cmd == "TEST START":
        water_module.start_test(pipeline=False, allow_outputs=False)
        return "Test mode started"
    elif cmd == "TEST START PIPE":
        water_module.start_test(pipeline=True, allow_outputs=False)
        return "Pipeline test started"
    elif cmd == "TEST START PIPE OUT":
        water_module.start_test(pipeline=True, allow_outputs=True)
        return "Pipeline test with outputs started"
    elif cmd == "TEST STOP":
        water_module.stop_test()
        return "Test mode stopped"
    elif cmd == "TEST?":
        # Return JSON for consistency with other status commands
        test_status = {
            "test_active": water_module.test_active,
            "test_data_active": getattr(water_module, 'test_data_active', False),
            "test_pipeline": getattr(water_module, 'test_pipeline', False),
            "test_allow_outputs": getattr(water_module, 'test_allow_outputs', False),
            "test_data_id": getattr(water_module, 'test_data_id', 0),
            "test_period_s": water_module.cfg.get("test_period_s", 20)
        }
        return ujson.dumps(test_status)
    elif cmd.startswith("TEST PERIOD "):
        # Dynamisch de sweep-periode aanpassen
        try:
            val = int(cmd.split()[-1])
            if val < 2:
                val = 2
            if val > 120:
                val = 120
            water_module.cfg["test_period_s"] = val
            # Reset starttijd zodat de nieuwe periode direct effect heeft
            water_module.test_start_time = time.time()
            # Forceer snelle feedback
            try:
                water_module._last_test_ble_ms = 0
                water_module._generate_test_data(force_send=True)
            except Exception:
                pass
            return f"Test period set to {val}s"
        except Exception as e:
            return f"Invalid period: {e}"
    elif cmd == "TEST FAST":
        water_module.cfg["test_period_s"] = 8
        water_module.test_start_time = time.time()
        try:
            water_module._last_test_ble_ms = 0
            water_module._generate_test_data(force_send=True)
        except Exception:
            pass
        return "Test period set to 8s"
    elif cmd == "INFO?":
        # Retourneer statusinformatie als JSON (dashboard verwacht JSON).
        # Tijdens test: gebruik test-niveau; anders echte sensor.
        if water_module.test_active and water_module.test_level is not None:
            # During test: use test level and state
            pct = water_module._update_level_state_from_level(water_module.test_level)
            current_level = water_module.test_level
            sensor_valid = True
        else:
            # Normal mode: use real sensor data
            pct = water_module._update_level_state()
            current_level = water_module.current_level if water_module.sensor_valid else None
            sensor_valid = bool(water_module.sensor_valid)
        
        # Mask percentage when sensor is invalid to avoid fake 0%/100% flicker
        pct_for_display = round(pct, 1) if sensor_valid else None
        
        import ujson
        info_data = {
            "pct": pct_for_display,
            "state": water_module.current_state,
            "ready": water_module.ready,
            "cal_empty_mm": water_module.cfg.get("cal_empty_mm", 190.0),
            "cal_full_mm": water_module.cfg.get("cal_full_mm", 50.0),
            "test_active": water_module.test_active,
            "current_level_mm": current_level,
            "sensor_valid": sensor_valid
        }
        return ujson.dumps(info_data)
    elif cmd == "CFG?":
        # Retourneer essentiële configuratie als JSON (dashboard verwacht JSON).
        import ujson
        essential_cfg = {
            "min_mm": water_module.cfg.get("min_mm", 0),
            "max_mm": water_module.cfg.get("max_mm", 100),
            "timeout_ms": water_module.cfg.get("timeout_ms", 1000),
            "sample_hz": water_module.cfg.get("sample_hz", 10),
            "hysteresis_pct": water_module.cfg.get("hysteresis_pct", 5),
            "low_pct": water_module.cfg.get("low_pct", 20),
            "bottom_pct": water_module.cfg.get("bottom_pct", 5),
            "ble_enabled": water_module.cfg.get("ble_enabled", True),
            "ble_name": water_module.cfg.get("ble_name", "VBMCSWT")
        }
        return ujson.dumps(essential_cfg)
    elif cmd == "CAL FULL":
        # Set current level as full calibration point
        if water_module.sensor_valid and water_module.current_level is not None:
            water_module.cfg["cal_full_mm"] = water_module.current_level
            if save_config():
                try:
                    # Push immediate status update so dashboard refreshes promptly
                    water_module._send_status()
                except Exception:
                    pass
                return f"Full level calibrated to {water_module.current_level:.1f}mm"
            else:
                return "Calibration set but failed to save config"
        else:
            return "Cannot calibrate: no valid sensor reading"
    elif cmd == "CAL EMPTY":
        # Set current level as empty calibration point
        if water_module.sensor_valid and water_module.current_level is not None:
            water_module.cfg["cal_empty_mm"] = water_module.current_level
            if save_config():
                try:
                    water_module._send_status()
                except Exception:
                    pass
                return f"Empty level calibrated to {water_module.current_level:.1f}mm"
            else:
                return "Calibration set but failed to save config"
        else:
            return "Cannot calibrate: no valid sensor reading"
    elif cmd == "CAL CLEAR":
        # Clear calibration values (reset to None/defaults)
        water_module.cfg["cal_full_mm"] = None
        water_module.cfg["cal_empty_mm"] = None
        if save_config():
            try:
                water_module._send_status()
            except Exception:
                pass
            return "Calibration cleared"
        else:
            return "Calibration cleared but failed to save config"
    elif cmd == "CFG RESET":
        # Reset configuration to defaults
        try:
            # Keep essential runtime state but reset config values
            old_ble_name = water_module.cfg.get("ble_name", "VBMCSWT")
            water_module.cfg.clear()
            water_module.cfg.update(DEFAULT_CONFIG.copy())
            
            # Save the reset config
            if save_config():
                try:
                    water_module._send_status()
                except Exception:
                    pass
                return f"Configuration reset to defaults (BLE name: {old_ble_name})"
            else:
                return "Configuration reset but failed to save"
        except Exception as e:
            return f"Failed to reset config: {e}"
    else:
        return f"Unknown command: {cmd}"

def main():
    """Start de module, bind de BLE-handler en ga de hoofdlus in."""
    global water_module
    
    log("info", "Starting WaterModule...")
    
    try:
        # Initialize the water module
        water_module = WaterModule()
        log("info", f"WaterModule initialized with config: {water_module.cfg}")
        
        # Bind the BLE command handler
        if water_module.ble:
            water_module.ble.on_command = handle_command
            log("info", "BLE command handler bound")
        
        log("info", "Starting main loop...")
        # Start the main loop
        water_module.run()
        
    except KeyboardInterrupt:
        log("info", "Stopped by user")
    except Exception as e:
        log("err", f"Fatal: {e}")
        # Set pins to safe state
        for pin_no in ("interlock_pin", "pump_ok_pin", "heater_ok_pin"):
            try:
                p = Pin(DEFAULT_CONFIG[pin_no], Pin.OUT)
                p.value(1)  # safe
                log("info", f"Pin {pin_no} set to safe")
            except Exception as pin_e:
                log("error", f"Failed to set pin {pin_no} safe: {pin_e}")
        raise

if __name__ == "__main__":
    main()
