import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from brontes.ledger import Ledger
from brontes.notifications import HermesCliNotificationDispatcher


class HermesCliNotificationDispatcherTests(unittest.TestCase):
    def test_delivers_pending_notification_and_marks_it_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                ledger.record_home_interval(
                    source_key="interval", started_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                    ended_at=datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc), energy_kwh=Decimal("1"),
                )
                ledger.record_agile_price(
                    settlement_start=datetime(2026, 9, 1, tzinfo=timezone.utc),
                    unit_price_p_per_kwh=Decimal("10"),
                )
                ledger.record_vehicle_observation(
                    observed_at=datetime(2026, 9, 1, 0, 31, tzinfo=timezone.utc),
                    soc_percent=Decimal("80"), odometer_miles=19044,
                )
                ledger.reconcile_odometer_change(
                    observed_at=datetime(2026, 9, 1, 1, tzinfo=timezone.utc), odometer_miles=19044
                )
                commands = []
                dispatcher = HermesCliNotificationDispatcher(
                    ledger, run=lambda command: commands.append(command) or '{"success":true}'
                )

                self.assertEqual(dispatcher.deliver_pending(), 1)
                self.assertEqual(ledger.pending_notification_count(), 0)
                self.assertEqual(commands[0][:4], ["hermes", "send", "--to", "telegram"])
            finally:
                ledger.close()
    def test_delivers_vw_poll_alert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                started = datetime(2026, 9, 1, tzinfo=timezone.utc)
                ledger.record_vw_poll_failure(observed_at=started)
                ledger.record_vw_poll_failure(observed_at=started.replace(hour=1))
                ledger.record_vw_poll_failure(observed_at=started.replace(hour=2))
                commands = []
                dispatcher = HermesCliNotificationDispatcher(
                    ledger, run=lambda command: commands.append(command) or '{"success":true}'
                )

                self.assertEqual(dispatcher.deliver_pending(), 1)
                self.assertEqual(ledger.pending_alerts(), [])
                self.assertIn("failed 3 consecutive times", commands[0][-1])
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
