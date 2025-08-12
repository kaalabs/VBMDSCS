import time


class DYPA02YY:
    """Driver for DYP-A02YY (UART) ultrasonic sensor.

    The sensor exists in binary and ASCII variants. We auto-detect a mode based
    on the incoming bytes, and then parse accordingly. For robustness, invalid
    frames are ignored and `None` is returned instead of raising.
    """

    def __init__(self, uart):
        self.uart = uart
        self.mode = None  # "bin" or "asc"
        self._last_detect_t = 0

    def _detect_mode(self, buf):
        """Guess protocol from a small sample buffer.

        - Binary frames look like: 0xFF 0xXX 0xMM 0xMM
        - ASCII streams contain digits separated by non-digits
        """
        if len(buf) >= 4 and buf[0] == 0xFF:
            mm = (buf[2] << 8) | buf[3]
            if 0 < mm < 10000:
                return "bin"
        for c in buf:
            if 48 <= c <= 57:
                return "asc"
        return None

    def read_mm(self):
        """Read the most recent distance in millimeters.

        Returns
        -------
        int | None
            Distance in mm, or None if no new valid reading is available.
        """
        n = self.uart.any()
        if n <= 0:
            return None
        data = self.uart.read(min(32, n))
        if not data:
            return None

        now = time.ticks_ms()
        if not self.mode or time.ticks_diff(now, self._last_detect_t) > 2000:
            m = self._detect_mode(data)
            if m:
                self.mode = m
                self._last_detect_t = now

        if self.mode == "bin":
            for i in range(len(data) - 3):
                if data[i] == 0xFF:
                    mm = (data[i+2] << 8) | data[i+3]
                    if 0 < mm < 10000:
                        return mm
            return None
        else:
            try:
                s = data.decode(errors="ignore")
                num = None
                acc = ""
                for ch in s:
                    if ch.isdigit():
                        acc += ch
                    else:
                        if acc:
                            num = int(acc)
                            acc = ""
                if acc:
                    num = int(acc)
                if num and 0 < num < 10000:
                    return num
            except Exception:
                pass
            return None
