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
        UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
        UART_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_NOTIFY)
        UART_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_WRITE)
        UART_SERVICE = (UART_UUID, (UART_TX, UART_RX))
        ((self.tx_handle, self.rx_handle),) = self.ble.gatts_register_services((UART_SERVICE,))
        self.connections = set()
        try:
            self.ble.gap_advertise(100_000, adv_data=self._adv_payload(name=self.name))
        except Exception:
            pass

    def _adv_payload(self, name=None):
        payload = bytearray(b"")
        if name:
            name_bytes = name.encode()
            payload += bytearray((len(name_bytes) + 1, 0x09)) + name_bytes
        return bytes(payload)

    def _irq(self, event, data):
        if event == 1:  # connect
            conn_handle, _, _ = data
            self.connections.add(conn_handle)
        elif event == 2:  # disconnect
            conn_handle, _, _ = data
            self.connections.discard(conn_handle)
            try:
                self.ble.gap_advertise(100_000, adv_data=self._adv_payload(name=self.name))
            except Exception:
                pass
        elif event == 3:  # write
            conn_handle, value_handle = data
            if value_handle == self.rx_handle:
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
        for c in self.connections:
            try:
                for i in range(0, len(data), chunk_size):
                    self.ble.gatts_notify(c, self.tx_handle, data[i:i + chunk_size])
                    try:
                        time.sleep_ms(5)
                    except Exception:
                        pass
            except Exception:
                pass
