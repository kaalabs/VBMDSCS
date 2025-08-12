from machine import Pin
from watertank_files.water_module import WaterModule, log, DEFAULT_CONFIG

# Try to initialize display
try:
    from watertank_files.display import get_display
    display = get_display(DEFAULT_CONFIG)
    if display:
        log("info", "Display initialized successfully")
    else:
        log("info", "Display not available")
except Exception as e:
    log("warn", f"Display init failed: {e}")

def main():
    mod = WaterModule()
    log("info", f"WaterModule starting with config: {mod.cfg}")
    
    # Update display with actual config if available
    try:
        if 'display' in globals() and display:
            from watertank_files.display import update_status, add_log_message
            update_status("Starting WaterTank module...", 0xFFFF00)
            add_log_message(f"Config loaded: {len(mod.cfg)} settings", "info")
    except Exception as e:
        log("warn", f"Display update failed: {e}")
    
    try:
        mod.run()
    except KeyboardInterrupt:
        log("info", "Stopped")
    except Exception as e:
        log("err", f"Fatal: {e}")
        for pin_no in ("interlock_pin", "pump_ok_pin", "heater_ok_pin"):
            try:
                p = Pin(DEFAULT_CONFIG[pin_no], Pin.OUT)
                p.value(1)  # safe
            except Exception:
                pass
        raise
    finally:
        # Cleanup display if available
        try:
            if 'display' in globals() and display:
                display.cleanup()
        except Exception as e:
            log("warn", f"Display cleanup failed: {e}")


if __name__ == "__main__":
    main()
