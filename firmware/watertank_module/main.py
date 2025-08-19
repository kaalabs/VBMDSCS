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

# Global reference to the water module
water_module = None

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
        status = "Test active" if water_module.test_active else "Test inactive"
        return f"Test status: {status}"
    elif cmd == "INFO?":
        # Retourneer statusinformatie als JSON (dashboard verwacht JSON).
        # Tijdens test: gebruik test-niveau; anders echte sensor.
        if water_module.test_active and water_module.test_level is not None:
            # During test: use test level and state
            pct = water_module._update_level_state_from_level(water_module.test_level)
            current_level = water_module.test_level
        else:
            # Normal mode: use real sensor data
            pct = water_module._update_level_state()
            current_level = water_module.current_level if water_module.sensor_valid else None
            
        import ujson
        info_data = {
            "pct": round(pct, 1),
            "state": water_module.current_state,
            "ready": water_module.ready,
            "cal_empty_mm": water_module.cfg.get("cal_empty_mm", water_module.cfg.get("max_mm", 0)),
            "cal_full_mm": water_module.cfg.get("cal_full_mm", water_module.cfg.get("min_mm", 0)),
            "test_active": water_module.test_active,
            "current_level_mm": current_level
        }
        return ujson.dumps(info_data)
    elif cmd == "CFG?":
        # Retourneer essentiële configuratie als JSON (dashboard verwacht JSON).
        import ujson
        essential_cfg = {
            "min_mm": water_module.cfg.get("min_mm", 0),
            "max_mm": water_module.cfg.get("max_mm", 100),
            "cal_empty_mm": water_module.cfg.get("cal_empty_mm", water_module.cfg.get("max_mm", 0)),
            "cal_full_mm": water_module.cfg.get("cal_full_mm", water_module.cfg.get("min_mm", 0)),
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
        # Gebruik EMA indien beschikbaar, anders huidige sensorwaarde
        lvl = water_module.ema_level if (water_module.ema_level is not None and water_module.sensor_valid) else water_module.current_level
        try:
            if lvl is not None:
                water_module.cfg["cal_full_mm"] = float(lvl)
                _save_cfg(water_module.cfg)
                return "CAL FULL saved"
            return "No level"
        except Exception as e:
            return f"CAL FULL error: {e}"
    elif cmd == "CAL EMPTY":
        lvl = water_module.ema_level if (water_module.ema_level is not None and water_module.sensor_valid) else water_module.current_level
        try:
            if lvl is not None:
                water_module.cfg["cal_empty_mm"] = float(lvl)
                _save_cfg(water_module.cfg)
                return "CAL EMPTY saved"
            return "No level"
        except Exception as e:
            return f"CAL EMPTY error: {e}"
    elif cmd == "CAL CLEAR":
        try:
            water_module.cfg["cal_full_mm"] = None
            water_module.cfg["cal_empty_mm"] = None
            _save_cfg(water_module.cfg)
            return "CAL cleared"
        except Exception as e:
            return f"CAL CLEAR error: {e}"
    elif cmd == "CFG RESET":
        try:
            # Reset naar DEFAULT_CONFIG en bewaar
            new_cfg = DEFAULT_CONFIG.copy()
            _save_cfg(new_cfg)
            # Forceer herladen in runtime zonder reboot
            water_module.cfg = new_cfg
            return "CFG reset"
        except Exception as e:
            return f"CFG RESET error: {e}"
    else:
        return f"Unknown command: {cmd}"

def _save_cfg(cfg):
    """Bewaar configuratie atomaal naar `persist_path`."""
    import ujson, os
    path = cfg.get("persist_path", "config.json")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(ujson.dumps(cfg))
        try:
            # Atomic replace wanneer mogelijk
            os.remove(path)
        except Exception:
            pass
        try:
            os.rename(tmp, path)
        except Exception:
            # Fallback copy
            with open(path, "w") as f:
                f.write(ujson.dumps(cfg))
            try:
                os.remove(tmp)
            except Exception:
                pass
    except Exception:
        # Laat fout bubbelen naar aanroeper
        raise

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
