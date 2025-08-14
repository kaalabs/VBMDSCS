"""Stub-driver voor de DYPA02YY afstandssensor.

Dit is een minimale placeholder zodat de module kan opstarten en BLE kan draaien
zonder echte sensor. Implementeer `read_mm()` om een float in millimeters terug
te geven wanneer de echte sensor wordt gekoppeld.
"""


class DYPA02YY:
    # Minimal stub driver; returns None so the module can boot and BLE can run
    def __init__(self, uart):
        self.uart = uart

    def read_mm(self):
        """Lees één meting in mm; retourneer `None` zolang er geen implementatie is."""
        return None
