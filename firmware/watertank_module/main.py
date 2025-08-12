from machine import Pin
from water_module import WaterModule, log, DEFAULT_CONFIG


def main():
    mod = WaterModule()
    log("info", f"WaterModule starting with config: {mod.cfg}")
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


if __name__ == "__main__":
    main()
