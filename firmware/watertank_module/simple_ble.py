"""Eenvoudige BLE-helper voor een Nordic UART-achtige service (NUS).

Overzicht
---------
- Biedt een BLE peripheral die tekstregels ontvangt (RX) en notificaties verstuurt (TX).
- RX: ontvangen bytes → UTF-8 decode → line framing op "\n" (CRLF toegestaan) →
  aanroep van ``on_command(str)`` per complete regel.
- TX: berichten worden in een kleine queue geplaatst met coalescing en pacing;
  verzending gebeurt in chunks voor compatibiliteit met ATT/MTU.

Compatibiliteit
---------------
- Werkt op MicroPython varianten/ports met kleine verschillen in GATT API's (handle-volgorde).
- Robuuste mapping van characteristic value handles (NOTIFY/WRITE) voor verschillende ports.
- Gebruikt ``micropython.schedule`` indien beschikbaar om vanuit IRQ-context veilig callbacks te plannen.

Ontwerpkeuzes
-------------
- Line-based command interface met een RX-accumulator begrensd op ~512 tekens.
- TX micro-queue (max 32 items) met drop-oudste bij overflow en lichte coalescing van kleine payloads.
- Chunks van 18 bytes per ``gatts_notify`` voor conservatieve compatibiliteit.
- Advertising met 128-bit NUS UUID en verkorte naam; interval ~500 ms.
 - Optionele rate limiter voor NOTIFY (``send_interval_ms``) om maximaal X ms tussen verzendingen te houden.
"""

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
    """Nordic-UART-achtige status/commandoservice voor eenvoudige tekst I/O.

    Functie-overzicht:
    - Advertise en expose een service met één RX (WRITE) en één TX (NOTIFY) characteristic
      met de Nordic UART UUID's.
    - Ontvangt inkomende tekstregels en roept ``on_command(str)`` aan per complete regel.
    - Verstuurt tekst via een kleine queue met chunking, pacing en eenvoudige coalescing.

    Belangrijke attributen:
    - ``name``: Apparatennaam voor GAP advertising.
    - ``connections``: Set met actieve connection handles.
    - ``_tx_queue``: Interne wachtrij met te verzenden bytestrings (max ``_queue_max`` items).
    - ``_chunk_size``: Grootte van een notify-chunk (conservatief 18 bytes).
    - ``_rx_accum``: Accumulator voor inkomende data tot een newline ("\n") wordt gezien.
    """

    def __init__(self, name="VBMCSWT", send_interval_ms=0):
        self.name = name
        # Optionele rate limiter voor NOTIFY: 0 = geen limiet
        try:
            self._send_interval_ms = max(0, int(send_interval_ms))
        except Exception:
            self._send_interval_ms = 0
        self._last_send_ms = 0
        self._rate_timer = None  # One-shot timer voor vertraagde drain
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

        # TX micro-queue & RX line framing
        self._tx_queue = []            # lijst met bytes-payloads in FIFO volgorde
        self._queue_max = 32           # max aantal wachtrij-items; drop oudste bij overflow
        self._chunk_size = 18          # chunkgrootte voor gatts_notify (conservatief vs. MTU)
        self._draining = False         # vlag of drain-loop reeds gepland/actief is
        self._rx_accum = ""            # buffer voor (deel)regels totdat een '\n' verschijnt

        # Ensure we start advertising immediately
        self._start_adv()

    def _now_ms(self):
        """Huidige tijd in milliseconden.

        Probeert ``time.ticks_ms`` (MicroPython) en valt terug op ``int(time.time()*1000)``
        voor omgevingen zonder ``ticks_ms``.
        """
        try:
            return time.ticks_ms()
        except Exception:
            # Fallback for environments without ticks_ms
            return int(time.time() * 1000)
        

    def _uuid128_le(self, uuid_str):
        """Converteer UUID-string naar 128-bit little-endian bytes (voor advertising)."""
        hexs = uuid_str.replace('-', '')
        buf = bytearray()
        for i in range(0, 32, 2):
            buf.append(int(hexs[i:i+2], 16))
        out = bytearray()
        for i in range(len(buf) - 1, -1, -1):
            out.append(buf[i])
        return bytes(out)

    def _adv_payload(self, name=None, services=None):
        """Bouw advertising payload (max 31 bytes): flags + (optioneel) 128-bit services + naam.

        - Flags 0x06: LE General Discoverable + BR/EDR Not Supported
        - 128-bit services (AD type 0x07) in LE bytevolgorde
        - Verkorte naam (AD type 0x08) binnen resterende ruimte
        """
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
        """Niet gebruikt: lege scan response voor brede port-compatibiliteit."""
        return b""

    def _start_adv(self):
        """Start (opnieuw) adverteren met NUS UUID en verkorte naam."""
        try:
            adv = self._adv_payload(name=self.name, services=[self._UART_UUID_STR])
            try:
                self.ble.gap_advertise(500_000, adv_data=adv, connectable=True)
            except Exception:
                self.ble.gap_advertise(500_000, adv_data=adv)
        except Exception:
            pass

    def _schedule_drain_after(self, delay_ms):
        """Plan een drain-iteratie na een vertraging met een one-shot timer indien beschikbaar."""
        try:
            from machine import Timer
        except Exception:
            return False
        try:
            # Stop bestaande timer indien actief
            if self._rate_timer is not None:
                try:
                    self._rate_timer.deinit()
                except Exception:
                    pass
                self._rate_timer = None
            self._rate_timer = Timer(-1)
            def _tmr_cb(_):
                try:
                    if micropython and hasattr(micropython, "schedule"):
                        def _run(_):
                            self._schedule_drain()
                        micropython.schedule(_run, 0)
                    else:
                        self._schedule_drain()
                except Exception:
                    pass
                try:
                    self._rate_timer.deinit()
                except Exception:
                    pass
                self._rate_timer = None
            self._rate_timer.init(period=max(1, int(delay_ms)), mode=Timer.ONE_SHOT, callback=_tmr_cb)
            return True
        except Exception:
            return False

    def _irq(self, event, data):
        """BLE IRQ handler: connect (1), disconnect (2), write (3)."""
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
                # Accumulate and frame by lines (\n). Tolerate CRLF.
                try:
                    self._rx_accum += raw.decode('utf-8', 'ignore')
                except Exception:
                    return
                # bound buffer to avoid unbounded growth
                if len(self._rx_accum) > 512:
                    self._rx_accum = self._rx_accum[-512:]
                while True:
                    nl = self._rx_accum.find('\n')
                    if nl < 0:
                        break
                    line = self._rx_accum[:nl]
                    self._rx_accum = self._rx_accum[nl+1:]
                    cmd_txt = line.replace('\r', '').strip()
                    if not cmd_txt:
                        continue
                    if micropython and hasattr(micropython, "schedule"):
                        # Use a scheduled callback with required single-arg signature
                        def _run_cmd_cb(_):
                            try:
                                response = self.on_command(cmd_txt)
                                if response:
                                    self.notify(response)
                            except Exception:
                                pass
                        try:
                            micropython.schedule(_run_cmd_cb, 0)
                        except Exception:
                            try:
                                response = self.on_command(cmd_txt)
                                if response:
                                    self.notify(response)
                            except Exception:
                                pass
                    else:
                        try:
                            response = self.on_command(cmd_txt)
                            if response:
                                self.notify(response)
                        except Exception:
                            pass

    def on_command(self, cmd):
        """Te overschrijven callback: verwerk één tekstregel als commando en
        retourneer optioneel een antwoord (``str`` of ``bytes``).
        """
        pass

    def notify(self, text):
        """Queueer een bericht voor TX via NOTIFY met coalescing en pacing."""
        if text is None:
            return
        data = text if isinstance(text, bytes) else text.encode()
        # Coalesce small payloads by appending when last item is small
        if self._tx_queue and (len(self._tx_queue[-1]) + len(data) <= 240):
            self._tx_queue[-1] += data
        else:
            self._tx_queue.append(data)
        # Prevent unbounded growth
        while len(self._tx_queue) > self._queue_max:
            try:
                self._tx_queue.pop(0)
            except Exception:
                break
        self._schedule_drain()

    def notify_priority(self, text):
        """Plaats bericht vooraan in de queue en start direct met verzenden."""
        if text is None:
            return
        data = text if isinstance(text, bytes) else text.encode()
        self._tx_queue.insert(0, data)
        while len(self._tx_queue) > self._queue_max:
            try:
                self._tx_queue.pop(1 if len(self._tx_queue) > 1 else 0)
            except Exception:
                break
        self._schedule_drain()

    def clear_tx_backlog(self):
        """Leeg de TX-wachtrij onmiddellijk om verouderde berichten te droppen."""
        try:
            self._tx_queue = []
        except Exception:
            pass

    def _schedule_drain(self):
        """Plan de drain-actie als deze nog niet actief is (eventueel met scheduling)."""
        if self._draining:
            return
        self._draining = True
        if micropython and hasattr(micropython, "schedule"):
            try:
                def _drain_cb(_):
                    self._drain_once()
                micropython.schedule(_drain_cb, 0)
                return
            except Exception:
                pass
        # Fallback: call inline
        self._drain_once()

    def _drain_once(self):
        """Eén drain-iteratie: coalesce en chunked-notify naar alle verbindingen.

        Zonder verbindingen wordt backlog gereduceerd tot het laatste item om geheugen te sparen.
        """
        # Respecteer optionele verzend-interval (rate limit)
        if self._send_interval_ms and self._tx_queue:
            now_ms = self._now_ms()
            try:
                elapsed = (now_ms - self._last_send_ms) if self._last_send_ms else self._send_interval_ms
            except Exception:
                elapsed = self._send_interval_ms
            if elapsed < self._send_interval_ms:
                remaining = self._send_interval_ms - elapsed
                # Stop huidige drain en plan later opnieuw
                self._draining = False
                if not self._schedule_drain_after(remaining):
                    # Zonder timer geen busy-wait doen; volgende notify triggert opnieuw
                    pass
                return
        try:
            # If no connections, drop old backlog but keep latest
            if not self.connections:
                if len(self._tx_queue) > 1:
                    self._tx_queue = self._tx_queue[-1:]
                self._draining = False
                return
            if not self._tx_queue:
                self._draining = False
                return
            # Pop one payload and (light) coalesce next small one
            payload = self._tx_queue.pop(0)
            if self._tx_queue and len(payload) < 64 and (len(payload) + len(self._tx_queue[0]) <= 240):
                try:
                    payload += self._tx_queue.pop(0)
                except Exception:
                    pass
            # Send to all connections in chunks
            for c in list(self.connections):
                try:
                    for i in range(0, len(payload), self._chunk_size):
                        self.ble.gatts_notify(c, self._tx_val_handle, payload[i:i+self._chunk_size])
                        try:
                            time.sleep_ms(5)
                        except Exception:
                            pass
                except Exception:
                    try:
                        self.connections.remove(c)
                    except Exception:
                        pass
            # Update laatst verzonden tijdstip na succesvolle verzending
            try:
                self._last_send_ms = self._now_ms()
            except Exception:
                self._last_send_ms = 0
        finally:
            # Reschedule if queue still has data
            if self._tx_queue and (micropython and hasattr(micropython, "schedule")):
                try:
                    def _drain_cb2(_):
                        self._drain_once()
                    micropython.schedule(_drain_cb2, 0)
                except Exception:
                    # Fallback immediate to avoid stall
                    self._drain_once()
            else:
                self._draining = False

