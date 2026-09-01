import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from brontes.ledger import Ledger
from brontes.myenergi import ZappiTelemetry
from brontes.polling import Poller
from brontes.vw import VehicleTelemetry


class PollerTests(unittest.TestCase):
    def test_persists_one_read_only_vw_and_zappi_poll(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                vw = type("Vw", (), {"read": lambda self: VehicleTelemetry(
                    source_timestamp=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
                    soc_percent=Decimal("34"), odometer_miles=18742,
                    charging_state="charging", charge_type="ac", charge_power_kw=Decimal("7.2"),
                )})()
                zappi = type("Zappi", (), {"read": lambda self: ZappiTelemetry(
                    device_id="123", connected=True, charging=True, power_kw=Decimal("7.2"),
                    session_energy_kwh=Decimal("1.2"),
                )})()

                result = Poller(ledger, vw, zappi).poll_once()

                self.assertTrue(result.vw_recorded)
                self.assertTrue(result.zappi_recorded)
                self.assertEqual(ledger.latest_zappi_state()["connected"], True)
                self.assertEqual(ledger.latest_zappi_state()["charging"], True)
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
