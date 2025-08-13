from machine import Pin
from water_module import WaterModule, log, DEFAULT_CONFIG
import time

# Global reference to the water module
water_module = None

def handle_command(cmd):
    """Handle incoming commands from BLE."""
    global water_module
    if not water_module:
        return "Water module not initialized"
    
    cmd = cmd.strip().upper()
    log("info", f"Received command: {cmd}")
    
    if cmd == "TEST START":
        water_module.start_test()
        return "Test mode started"
    elif cmd == "TEST STOP":
        water_module.stop_test()
        return "Test mode stopped"
    elif cmd == "TEST?":
        status = "Test active" if water_module.test_active else "Test inactive"
        return f"Test status: {status}"
    elif cmd == "INFO?":
        # Return current status info as JSON (dashboard expects JSON)
        # Use test data if in test mode, otherwise real sensor data
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
            "cal_empty_mm": water_module.cfg.get("min_mm", 0),
            "cal_full_mm": water_module.cfg.get("max_mm", 100),
            "test_active": water_module.test_active,
            "current_level_mm": current_level
        }
        return ujson.dumps(info_data)
    elif cmd == "CFG?":
        # Return essential config as JSON (dashboard expects JSON) 
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
    else:
        return f"Unknown command: {cmd}"

def main():
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
