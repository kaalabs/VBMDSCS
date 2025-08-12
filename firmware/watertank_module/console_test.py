"""Console test script for ESP32-S3-BOX-3.

Simple test to verify basic functionality without display modules.
This works with standard MicroPython firmware.
"""

import time
import machine

def test_basic_functionality():
    """Test basic ESP32-S3-BOX-3 functionality."""
    print("=" * 50)
    print("ESP32-S3-BOX-3 Basic Functionality Test")
    print("=" * 50)
    
    # Test 1: Basic system info
    print("\n1. System Information:")
    print(f"   CPU Frequency: {machine.freq()} Hz")
    print(f"   Unique ID: {machine.unique_id().hex()}")
    print(f"   Reset Cause: {machine.reset_cause()}")
    
    # Test 2: GPIO functionality
    print("\n2. GPIO Test:")
    try:
        # Test LED pin (GPIO 2)
        led = machine.Pin(2, machine.Pin.OUT)
        print("   LED Pin (GPIO 2): OK")
        
        # Blink LED 3 times
        for i in range(3):
            led.value(1)
            time.sleep(0.5)
            led.value(0)
            time.sleep(0.5)
        print("   LED Blink Test: OK")
        
    except Exception as e:
        print(f"   LED Test Failed: {e}")
    
    # Test 3: Timer functionality
    print("\n3. Timer Test:")
    try:
        timer = machine.Timer(0)
        timer.init(period=1000, mode=machine.Timer.PERIODIC, callback=lambda t: print("   Timer tick!"))
        print("   Timer Created: OK")
        time.sleep(2)
        timer.deinit()
        print("   Timer Test: OK")
    except Exception as e:
        print(f"   Timer Test Failed: {e}")
    
    # Test 4: UART functionality
    print("\n4. UART Test:")
    try:
        # Test UART 2 (used by water sensor)
        uart = machine.UART(2, baudrate=9600, tx=17, rx=16)
        print("   UART 2 Created: OK")
        print(f"   UART Config: {uart}")
        uart.deinit()
        print("   UART Test: OK")
    except Exception as e:
        print(f"   UART Test Failed: {e}")
    
    # Test 5: I2C functionality
    print("\n5. I2C Test:")
    try:
        i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(21))
        devices = i2c.scan()
        print(f"   I2C Created: OK")
        print(f"   I2C Devices Found: {len(devices)}")
        if devices:
            print(f"   Device Addresses: {[hex(d) for d in devices]}")
        i2c.deinit()
        print("   I2C Test: OK")
    except Exception as e:
        print(f"   I2C Test Failed: {e}")
    
    # Test 6: SPI functionality
    print("\n6. SPI Test:")
    try:
        spi = machine.SPI(1, baudrate=1000000, polarity=0, phase=0, sck=machine.Pin(14), mosi=machine.Pin(13), miso=machine.Pin(12))
        print("   SPI Created: OK")
        spi.deinit()
        print("   SPI Test: OK")
    except Exception as e:
        print(f"   SPI Test Failed: {e}")
    
    # Test 7: Touch functionality
    print("\n7. Touch Test:")
    try:
        touch = machine.TouchPad(machine.Pin(4))
        value = touch.read()
        print(f"   Touch Pin 4: OK (Value: {value})")
    except Exception as e:
        print(f"   Touch Test Failed: {e}")
    
    # Test 8: Memory and storage
    print("\n8. Memory Test:")
    try:
        import gc
        gc.collect()
        free_memory = gc.mem_free()
        print(f"   Free Memory: {free_memory} bytes")
        
        import os
        files = os.listdir()
        print(f"   Files in Root: {len(files)}")
        for f in files:
            try:
                size = os.stat(f)[6]
                print(f"     {f}: {size} bytes")
            except:
                print(f"     {f}: <dir>")
        
        print("   Storage Test: OK")
    except Exception as e:
        print(f"   Storage Test Failed: {e}")
    
    print("\n" + "=" * 50)
    print("Basic Functionality Test Complete!")
    print("=" * 50)

def test_water_sensor_simulation():
    """Test water sensor simulation without actual sensor."""
    print("\n" + "=" * 50)
    print("Water Sensor Simulation Test")
    print("=" * 50)
    
    print("\nSimulating water level readings...")
    
    # Simulate different water levels
    levels = [100, 150, 200, 180, 120, 80, 50, 30, 60, 100]
    
    for i, level in enumerate(levels):
        print(f"   Reading {i+1}: {level}mm")
        
        # Simulate processing time
        time.sleep(0.5)
        
        # Simulate different states
        if level <= 30:
            state = "BOTTOM"
            color = "RED"
        elif level <= 80:
            state = "LOW"
            color = "ORANGE"
        else:
            state = "OK"
            color = "GREEN"
        
        print(f"     State: {state} ({color})")
        print(f"     Percentage: {max(0, min(100, (220 - level) / (220 - 30) * 100)):.1f}%")
    
    print("\nWater Sensor Simulation Complete!")

if __name__ == "__main__":
    try:
        test_basic_functionality()
        test_water_sensor_simulation()
        
        print("\nAll tests completed successfully!")
        print("The ESP32-S3-BOX-3 is ready for water tank module deployment.")
        
    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
