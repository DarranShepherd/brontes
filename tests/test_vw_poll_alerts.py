import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from brontes.ledger import Ledger

UTC = timezone.utc


class VwPollAlertTests(unittest.TestCase):
    def test_alerts_on_third_failure_then_daily_until_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                started = datetime(2026, 9, 1, 12, tzinfo=UTC)

                self.assertFalse(ledger.record_vw_poll_failure(observed_at=started))
                self.assertFalse(ledger.record_vw_poll_failure(observed_at=started + timedelta(minutes=15)))
                self.assertTrue(ledger.record_vw_poll_failure(observed_at=started + timedelta(minutes=30)))
                self.assertEqual(len(ledger.pending_alerts()), 1)
                self.assertFalse(ledger.record_vw_poll_failure(observed_at=started + timedelta(hours=23)))
                self.assertTrue(ledger.record_vw_poll_failure(observed_at=started + timedelta(hours=24, minutes=30)))
                self.assertEqual(len(ledger.pending_alerts()), 2)

                self.assertTrue(ledger.record_vw_poll_success(observed_at=started + timedelta(hours=25)))
                self.assertIn("recovered", ledger.pending_alerts()[-1].message.lower())
                self.assertFalse(ledger.record_vw_poll_success(observed_at=started + timedelta(hours=26)))
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
