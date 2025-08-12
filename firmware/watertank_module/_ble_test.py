try:
    import bluetooth
    import time
except Exception as e:
    print("ERR import", e)
    raise SystemExit

NAME = "VBMDSCSWT"

def adv_payload(name=None, services=None):
    p = bytearray()
    # Flags
    p += b"\x02\x01\x06"
    # Shortened name (to fit with service list if needed)
    if name:
        nb = name.encode()
        rem = 31 - len(p)
        maxc = max(0, rem - 2)
        if maxc:
            short = nb[:maxc]
            p += bytes((len(short) + 1, 0x08)) + short
    # 128-bit service UUIDs (complete list)
    if services:
        svc = bytearray()
        for u in services:
            try:
                raw = bytes.fromhex(u.replace('-', ''))
                svc += raw[::-1]
            except Exception:
                pass
        if svc:
            p += bytes((len(svc) + 1, 0x07)) + svc
    return bytes(p)

def main():
    ble = bluetooth.BLE()
    ble.active(True)
    try:
        ble.config(gap_name=NAME)
    except Exception:
        pass

    NUS = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
    uart_uuid = bluetooth.UUID(NUS)
    tx = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_NOTIFY)
    rx = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_WRITE)
    svc = (uart_uuid, (tx, rx))
    ble.gatts_register_services((svc,))

    adv = adv_payload(name=NAME, services=[NUS])
    try:
        ble.gap_advertise(500_000, adv_data=adv, connectable=True)
    except TypeError:
        ble.gap_advertise(500_000, adv_data=adv)

    print("ble_test_ok", len(adv))

if __name__ == "__main__":
    main()


