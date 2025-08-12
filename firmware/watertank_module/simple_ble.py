import time

try:
    import bluetooth
except ImportError:
    bluetooth = None  # BLE optional for early bring-up

try:
    import micropython
except Exception:
    micropython = None


class SimpleBLE:
    """Minimal Nordic-UART-style BLE status/command service."""

    def __init__(self, name="VBMDSCSWT"):
        self.name = name
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        try:
            self.ble.config(gap_name=self.name)
        except Exception:
            pass
        self.ble.irq(self._irq)

        # Nordic UART Service UUIDs
        self._UART_UUID_STR = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
        UART_UUID = bluetooth.UUID(self._UART_UUID_STR)
        UART_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_NOTIFY)
        UART_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_WRITE)
        UART_SERVICE = (UART_UUID, (UART_TX, UART_RX))
        # Register service and keep characteristic value handles (robust across ports)
        service_handles = self.ble.gatts_register_services((UART_SERVICE,))[0]
        # MicroPython may return (tx_val, tx_cccd, rx_val) for (NOTIFY, WRITE)
        # or just (tx_val, rx_val). Map accordingly.
        if isinstance(service_handles, (tuple, list)):
            if len(service_handles) >= 3:
                self._tx_val_handle = service_handles[0]
                self._rx_val_handle = service_handles[2]
            elif len(service_handles) == 2:
                self._tx_val_handle = service_handles[0]
                self._rx_val_handle = service_handles[1]
            else:
                # Fallback: assume first is TX, even if malformed
                self._tx_val_handle = service_handles[0] if len(service_handles) else None
                self._rx_val_handle = None
        else:
            # Unexpected shape; best effort
            self._tx_val_handle = service_handles
            self._rx_val_handle = None
        self.connections = set()
        try:
            adv = self._adv_payload(name=self.name, services=[self._UART_UUID_STR])
            try:
                self.ble.gap_advertise(500_000, adv_data=adv, connectable=True)
            except Exception:
                self.ble.gap_advertise(500_000, adv_data=adv)
        except Exception:
            pass

    def _uuid128_le(self, uuid_str):
        """Convert UUID string to 128-bit little-endian bytes without slicing step."""
        hexs = uuid_str.replace('-', '')
        buf = bytearray()
        for i in range(0, 32, 2):
            buf.append(int(hexs[i:i+2], 16))
        out = bytearray()
        for i in range(len(buf) - 1, -1, -1):
            out.append(buf[i])
        return bytes(out)

    def _adv_payload(self, name=None, services=None):
        # Build advertising payload within 31 bytes: flags + 128-bit services + shortened name
        payload = bytearray()
        # Flags: 0x06 = LE General Discoverable + BR/EDR Not Supported
        payload += b"\x02\x01\x06"
        # Services first (Complete List of 128-bit UUIDs)
        if services:
            svc_bytes = bytearray()
            for u in services:
                try:
                    svc_bytes += self._uuid128_le(u)
                except Exception:
                    continue
            if svc_bytes:
                ln = len(svc_bytes) + 1
                payload += bytes((ln, 0x07)) + svc_bytes
        # Shortened name fits in remaining budget
        if name:
            name_bytes = name.encode()
            remaining = 31 - len(payload)
            max_chars = remaining - 2
            if max_chars > 0:
                short = name_bytes[:max_chars]
                payload += bytes((len(short) + 1, 0x08)) + short
        return bytes(payload)

    def _scan_resp_payload(self, name=None):
        # Not used for maximum compatibility across ports
        return b""

    def _start_adv(self):
        try:
            adv = self._adv_payload(name=self.name, services=[self._UART_UUID_STR])
            try:
                self.ble.gap_advertise(500_000, adv_data=adv, connectable=True)
            except Exception:
                self.ble.gap_advertise(500_000, adv_data=adv)
        except Exception:
            pass

    def _irq(self, event, data):
        if event == 1:  # connect
            conn_handle, _, _ = data
            self.connections.add(conn_handle)
        elif event == 2:  # disconnect
            conn_handle, _, _ = data
            self.connections.discard(conn_handle)
            self._start_adv()
        elif event == 3:  # write
            conn_handle, value_handle = data
            if value_handle == self._rx_val_handle:
                try:
                    raw = self.ble.gatts_read(value_handle)
                except Exception:
                    raw = None
                if not raw:
                    return
                cmd_txt = None
                try:
                    cmd_txt = raw.decode().strip()
                except Exception:
                    return
                if micropython and hasattr(micropython, "schedule"):
                    def _run_cmd(_):
                        try:
                            self.on_command(cmd_txt)
                        except Exception:
                            pass
                    try:
                        micropython.schedule(_run_cmd, 0)
                    except Exception:
                        try:
                            self.on_command(cmd_txt)
                        except Exception:
                            pass
                else:
                    try:
                        self.on_command(cmd_txt)
                    except Exception:
                        pass

    def on_command(self, cmd):
        """Override to handle commands."""
        pass

    def notify(self, text):
        if text is None:
            return
        data = text if isinstance(text, bytes) else text.encode()
        chunk_size = 18
        for c in list(self.connections):
            try:
                for i in range(0, len(data), chunk_size):
                    self.ble.gatts_notify(c, self._tx_val_handle, data[i:i + chunk_size])
                    try:
                        time.sleep_ms(5)
                    except Exception:
                        pass
            except Exception:
                pass
