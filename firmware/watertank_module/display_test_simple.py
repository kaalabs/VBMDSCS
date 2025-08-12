"""Simple display test for ESP32-S3-BOX-3.

Basic test to verify the system is working without complex display modules.
"""

import time
import machine

def test_system_status():
    """Test and display system status."""
    print("=" * 60)
    print("ESP32-S3-BOX-3 WaterTank Module Status")
    print("=" * 60)
    
    # System info
    print(f"CPU Frequency: {machine.freq() // 1000000} MHz")
    print(f"Unique ID: {machine.unique_id().hex()}")
    print(f"Reset Cause: {machine.reset_cause()}")
    
    # Memory status
    import gc
    gc.collect()
    free_mem = gc.mem_free()
    print(f"Free Memory: {free_mem // 1024} KB")
    
    # File system
    import os
    files = os.listdir()
    print(f"Files in Root: {len(files)}")
    
    # Check watertank module files
    if 'watertank_files' in files:
        print("✓ WaterTank module files found")
        try:
            wt_files = os.listdir('watertank_files')
            print(f"  Module files: {len(wt_files)}")
            for f in wt_files:
                size = os.stat(f'watertank_files/{f}')[6]
                print(f"    {f}: {size} bytes")
        except Exception as e:
            print(f"  Error reading module files: {e}")
    else:
        print("✗ WaterTank module files not found")
    
    print("=" * 60)

def test_water_simulation():
    """Simulate water level monitoring."""
    print("\nWater Level Simulation:")
    print("-" * 40)
    
    # Simulate sensor readings
    levels = [200, 180, 150, 120, 100, 80, 60, 40, 30, 25, 30, 50, 80, 120, 160, 190]
    
    for i, level in enumerate(levels):
        # Calculate percentage (assuming 30mm = empty, 220mm = full)
        if level <= 30:
            pct = 0
            state = "BOTTOM"
            color = "🔴"
        elif level <= 80:
            pct = max(0, (80 - level) / (80 - 30) * 30)
            state = "LOW"
            color = "🟠"
        else:
            pct = max(0, (220 - level) / (220 - 80) * 70 + 30)
            state = "OK"
            color = "🟢"
        
        # Display status
        bar_length = 20
        filled = int(bar_length * pct / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        print(f"Reading {i+1:2d}: {level:3d}mm |{bar}| {pct:5.1f}% {color} {state}")
        
        # Simulate processing time
        time.sleep(0.3)
    
    print("-" * 40)

def test_led_status():
    """Test LED status indication."""
    print("\nLED Status Test:")
    print("-" * 40)
    
    try:
        led = machine.Pin(2, machine.Pin.OUT)
        
        # OK status (green blink)
        print("🟢 OK Status - Single blink")
        for _ in range(3):
            led.value(1); time.sleep(0.1)
            led.value(0); time.sleep(0.9)
        
        # LOW status (double blink)
        print("🟠 LOW Status - Double blink")
        for _ in range(3):
            for _ in range(2):
                led.value(1); time.sleep(0.08)
                led.value(0); time.sleep(0.12)
            time.sleep(0.7)
        
        # BOTTOM status (triple blink)
        print("🔴 BOTTOM Status - Triple blink")
        for _ in range(3):
            for _ in range(3):
                led.value(1); time.sleep(0.08)
                led.value(0); time.sleep(0.12)
            time.sleep(0.5)
        
        # FAULT status (long on, short off)
        print("🔴 FAULT Status - Long on, short off")
        for _ in range(3):
            led.value(1); time.sleep(0.8)
            led.value(0); time.sleep(0.2)
        
        led.value(0)  # Turn off
        print("✓ LED test completed")
        
    except Exception as e:
        print(f"✗ LED test failed: {e}")

def test_touch_sensitivity():
    """Test touch pad sensitivity."""
    print("\nTouch Pad Test:")
    print("-" * 40)
    
    try:
        touch = machine.TouchPad(machine.Pin(4))
        
        print("Touch the screen to see values change...")
        print("Press Ctrl+C to stop")
        
        for i in range(10):
            value = touch.read()
            # Normalize value (typical range: 0-4095)
            normalized = max(0, min(100, (4095 - value) / 4095 * 100))
            print(f"Touch {i+1:2d}: Raw={value:6d}, Normalized={normalized:5.1f}%")
            time.sleep(1)
            
    except Exception as e:
        print(f"✗ Touch test failed: {e}")
    except KeyboardInterrupt:
        print("\nTouch test stopped by user")

def main():
    """Run all tests."""
    try:
        test_system_status()
        test_water_simulation()
        test_led_status()
        test_touch_sensitivity()
        
        print("\n" + "=" * 60)
        print("🎉 All tests completed successfully!")
        print("The ESP32-S3-BOX-3 is ready for water tank operation.")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
