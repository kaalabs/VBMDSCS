"""Signaalbewerking en toestandsbesluit voor watertankniveau.

Deze module bevat een eenvoudige filterpijplijn (median + EMA) en een
hysterese-gebaseerde toestandsmachine (OK/LOW/BOTTOM/FAULT). De pijplijn is
geschikt voor lage samplefrequenties en beperkt geheugen.
"""

STATE_OK = "OK"
STATE_LOW = "LOW"
STATE_BOTTOM = "BOTTOM"
STATE_FAULT = "FAULT"


def clamp(x, a, b):
    """Beperk `x` tot het gesloten interval [a, b]."""
    return a if x < a else (b if x > b else x)


class LevelEstimator:
    """Kleine helperklasse om ruwe mm-metingen te filteren en te mappen naar %.

    Attributen (kern):
    - `window`: buffer voor medianfilter
    - `ema`: laatste geëxponentieel gewogen gemiddelde
    - `obs_min`/`obs_max`: optionele auto-leer ankers
    - `state`: laatst besloten toestand
    - `last_pct`: laatst berekende percentage
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.window = []
        self.ema = None
        self.obs_min = None
        self.obs_max = None
        self.state = STATE_FAULT
        self.last_pct = None

    def _median(self, arr):
        """Bereken de mediaan van een kleine lijst (copy/sort; n is klein)."""
        a = sorted(arr)
        n = len(a)
        if n == 0:
            return None
        mid = n // 2
        return a[mid] if n % 2 == 1 else (a[mid - 1] + a[mid]) / 2

    def ingest_mm(self, mm):
        """Verwerk ruwe mm-invoer door de pijplijn en geef (ema_mm, pct) terug.

        Stappen: plausibiliteit → mediaan → EMA → percent mapping.
        Bij ontbrekende kalibratie-ankers valt de mapping terug op `obs_min/max`.
        """
        if mm is None:
            return None, None
        if not (self.cfg["min_mm"] <= mm <= self.cfg["max_mm"]):
            return None, None

        self.window.append(mm)
        if len(self.window) > max(3, self.cfg["window"]):
            self.window.pop(0)
        med = self._median(self.window)
        if med is None:
            return None, None

        a = self.cfg["ema_alpha"]
        self.ema = med if self.ema is None else (a * med + (1 - a) * self.ema)

        if self.cfg["cal_auto_learn"]:
            if (self.obs_min is None) or (self.ema < self.obs_min):
                self.obs_min = self.ema
            if (self.obs_max is None) or (self.ema > self.obs_max):
                self.obs_max = self.ema

        empty_mm = self.cfg["cal_empty_mm"] if self.cfg["cal_empty_mm"] is not None else (self.obs_max or self.cfg["max_mm"])
        full_mm = self.cfg["cal_full_mm"] if self.cfg["cal_full_mm"] is not None else (self.obs_min or self.cfg["min_mm"])
        span = max(5.0, float(empty_mm - full_mm))
        pct = 100.0 * (empty_mm - float(self.ema)) / span
        pct = clamp(pct, 0.0, 100.0)

        self.last_pct = pct
        return self.ema, pct

    def decide_state(self):
        """Toestandsmachine met hysterese op basis van `last_pct`."""
        if self.last_pct is None:
            return STATE_FAULT
        low = self.cfg["low_pct"]
        bottom = self.cfg["bottom_pct"]
        h = self.cfg["hysteresis_pct"]
        cur = self.state
        p = self.last_pct

        if cur == STATE_FAULT:
            if p <= bottom:
                return STATE_BOTTOM
            elif p <= low:
                return STATE_LOW
            else:
                return STATE_OK

        if cur == STATE_OK:
            if p <= (low - h):
                return STATE_LOW
            return STATE_OK

        if cur == STATE_LOW:
            if p <= (bottom - h):
                return STATE_BOTTOM
            elif p >= (low + h):
                return STATE_OK
            return STATE_LOW

        if cur == STATE_BOTTOM:
            if p >= (bottom + h + h):
                return STATE_LOW if p <= (low - h) else STATE_OK
            return STATE_BOTTOM

        return STATE_FAULT
