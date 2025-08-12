"""Display test script for ESP32-S3-BOX-3.

Simple test to verify the display is working correctly.
Run this directly on the ESP32-S3-BOX-3 to test the display.
"""

import time
import lvgl as lv

def test_display():
    """Test basic display functionality."""
    print("Starting display test...")
    
    try:
        # Initialize display
        from display import WaterTankDisplay
        
        # Create display with test config
        config = {
            "display_brightness": 80,
            "display_timeout_s": 0
        }
        
        display = WaterTankDisplay(config)
        display.show_screen()
        
        print("Display initialized successfully")
        
        # Test tank level updates
        for i in range(0, 101, 10):
            display.update_tank_level(i, 100 + i)
            display.update_status(f"Test Level: {i}%")
            display.add_log_message(f"Level test: {i}%", "info")
            time.sleep(1)
        
        # Test status updates
        statuses = [
            ("OK - Normal Operation", 0x00FF00),
            ("LOW - Heater Disabled", 0xFF8800),
            ("BOTTOM - All Systems Off", 0xFF0000),
            ("FAULT - Check Sensor", 0xFF0000),
            ("TEST MODE - Synthetic Data", 0x0088FF)
        ]
        
        for status, color in statuses:
            display.update_status(status, color)
            display.add_log_message(f"Status: {status}", "info")
            time.sleep(2)
        
        # Test log messages
        log_messages = [
            ("System startup complete", "info"),
            ("Sensor reading: 150mm", "info"),
            ("Calibration updated", "info"),
            ("Warning: Low level detected", "warn"),
            ("Error: Sensor timeout", "err"),
            ("BLE connection established", "info"),
            ("Test mode activated", "info"),
            ("All systems operational", "info")
        ]
        
        for msg, level in log_messages:
            display.add_log_message(msg, level)
            time.sleep(1)
        
        print("Display test completed successfully")
        
        # Keep display active for a while
        time.sleep(5)
        
    except Exception as e:
        print(f"Display test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        try:
            if 'display' in locals():
                display.cleanup()
                print("Display cleaned up")
        except Exception as e:
            print(f"Display cleanup failed: {e}")

if __name__ == "__main__":
    test_display()
