import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from brontes.ledger import Ledger
from brontes.myenergi import ZappiTelemetry
from brontes.workflow import HomeChargingWorkflow

UTC = timezone.utc


class _Rates:
    def prices_between(self, start, end):
        cursor = start.replace(minute=(start.minute // 30) * 30, second=0, microsecond=0)
        prices = {}
        while cursor < end:
            prices[cursor] = Decimal("10")
            cursor = cursor.replace(minute=cursor.minute + 30) if cursor.minute == 0 else cursor.replace(hour=cursor.hour + 1, minute=0)
        return prices


class _ToggleRates(_Rates):
    available = False

    def prices_between(self, start, end):
        return super().prices_between(start, end) if self.available else {}


def _zappi(*, connected: bool, charging: bool, energy: str) -> ZappiTelemetry:
    return ZappiTelemetry(
        device_id="zappi-1",
        connected=connected,
        charging=charging,
        power_kw=Decimal("7.2") if charging else Decimal("0"),
        session_energy_kwh=Decimal(energy),
    )


class HomeSessionWorkflowTests(unittest.TestCase):
    def test_split_budget_charge_is_consolidated_only_after_unplug(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                workflow = HomeChargingWorkflow(ledger, _Rates())
                ledger.record_vehicle_observation(
                    observed_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
                    soc_percent=Decimal("50"),
                    odometer_miles=19044,
                )
                workflow.process_zappi(_zappi(connected=True, charging=True, energy="0"), datetime(2026, 9, 1, 0, 0, tzinfo=UTC))
                workflow.process_zappi(_zappi(connected=True, charging=True, energy="2"), datetime(2026, 9, 1, 0, 30, tzinfo=UTC))
                workflow.process_zappi(_zappi(connected=True, charging=False, energy="2"), datetime(2026, 9, 1, 1, 0, tzinfo=UTC))
                workflow.process_zappi(_zappi(connected=True, charging=True, energy="2"), datetime(2026, 9, 1, 2, 0, tzinfo=UTC))
                workflow.process_zappi(_zappi(connected=True, charging=True, energy="4"), datetime(2026, 9, 1, 2, 30, tzinfo=UTC))
                workflow.process_zappi(_zappi(connected=True, charging=False, energy="4"), datetime(2026, 9, 1, 3, 0, tzinfo=UTC))

                self.assertEqual(ledger.pending_notification_count(), 0)

                completed = workflow.process_zappi(
                    _zappi(connected=False, charging=False, energy="4"),
                    datetime(2026, 9, 1, 3, 30, tzinfo=UTC),
                )

                self.assertEqual(len(completed), 1)
                self.assertEqual(completed[0].energy_kwh, Decimal("4"))
                self.assertEqual(completed[0].total_cost_gbp, Decimal("0.40"))
                self.assertEqual(ledger.pending_notification_count(), 1)
            finally:
                ledger.close()

    def test_unpriced_session_is_retried_after_octopus_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                rates = _ToggleRates()
                workflow = HomeChargingWorkflow(ledger, rates)
                ledger.record_vehicle_observation(
                    observed_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
                    soc_percent=Decimal("50"), odometer_miles=19044,
                )
                workflow.process_zappi(_zappi(connected=True, charging=True, energy="0"), datetime(2026, 9, 1, 0, 0, tzinfo=UTC))
                workflow.process_zappi(_zappi(connected=True, charging=True, energy="2"), datetime(2026, 9, 1, 0, 30, tzinfo=UTC))
                self.assertEqual(
                    workflow.process_zappi(_zappi(connected=False, charging=False, energy="2"), datetime(2026, 9, 1, 1, 0, tzinfo=UTC)),
                    [],
                )

                rates.available = True
                completed = workflow.process_zappi(
                    _zappi(connected=False, charging=False, energy="2"),
                    datetime(2026, 9, 1, 1, 2, tzinfo=UTC),
                )

                self.assertEqual(len(completed), 1)
                self.assertEqual(completed[0].total_cost_gbp, Decimal("0.20"))
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
