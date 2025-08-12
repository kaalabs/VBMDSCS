import bluetooth
b = bluetooth.BLE(); b.active(True)
try:
    b.config(gap_name="VBMDSCSWT")
except Exception:
    pass
tx = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), 16)
rx = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), 8)
b.gatts_register_services(((bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E"), (tx, rx)),))
name = b"VBMDSCSWT"
hexs = "6E400001B5A3F393E0A9E50E24DCCA9E"
buf = bytearray()
for i in range(0, 32, 2):
    buf.append(int(hexs[i:i+2], 16))
svc = bytes(buf)[::-1]
adv = b"\x02\x01\x06" + bytes((len(name) + 1, 0x08)) + name + bytes((len(svc) + 1, 0x07)) + svc
try:
    b.gap_advertise(500000, adv_data=adv, connectable=True)
except Exception:
    b.gap_advertise(500000, adv_data=adv)
print("NUS adv started")
