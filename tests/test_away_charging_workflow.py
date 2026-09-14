import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from brontes.ledger import Ledger
from brontes.vw import VehicleTelemetry
from brontes.workflow import HomeChargingWorkflow

UTC = timezone.utc


class _Rates:
    def prices_between(self, start, end):
        return {}


def _vehicle(timestamp: datetime, soc: str, odometer: int) -> VehicleTelemetry:
    return VehicleTelemetry(
        source_timestamp=timestamp,
        soc_percent=Decimal(soc),
        odometer_miles=odometer,
        charging_state=None,
        charge_type=None,
        charge_power_kw=None,
    )


class AwayChargingWorkflowTests(unittest.TestCase):
    def test_creates_ac_and_dc_away_sessions_from_confirmed_soc_rises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                workflow = HomeChargingWorkflow(ledger, _Rates())
                samples = [
                    _vehicle(datetime(2026, 9, 12, 10, 36, tzinfo=UTC), "27", 19285),
                    _vehicle(datetime(2026, 9, 12, 14, 57, tzinfo=UTC), "36", 19285),
                    _vehicle(datetime(2026, 9, 13, 10, 29, tzinfo=UTC), "25", 19306),
                    _vehicle(datetime(2026, 9, 13, 11, 25, tzinfo=UTC), "36", 19306),
                    _vehicle(datetime(2026, 9, 13, 18, 21, tzinfo=UTC), "26", 19312),
                    _vehicle(datetime(2026, 9, 13, 18, 48, tzinfo=UTC), "55", 19321),
                ]

                completed = []
                for sample in samples:
                    completed.extend(workflow.process_vehicle(sample))

                self.assertEqual(len(completed), 3)
                self.assertEqual([session.location_type for session in completed], ["away", "away", "away"])
                self.assertEqual([session.energy_kwh for session in completed], [
                    Decimal("7.74"), Decimal("9.46"), Decimal("24.94")
                ])
                self.assertEqual([session.total_cost_gbp for session in completed], [
                    Decimal("2.02"), Decimal("2.47"), Decimal("18.71")
                ])
                notifications = ledger.pending_notifications()
                self.assertEqual(len(notifications), 3)
                self.assertIn("Away · AC · estimated", notifications[0].message)
                self.assertIn("VW SoC: 27% → 36%", notifications[0].message)
                self.assertIn("26.11p/kWh", notifications[0].message)
                self.assertIn("Away · DC · estimated", notifications[2].message)
                self.assertIn("VW SoC: 26% → 55%", notifications[2].message)
                self.assertIn("75.00p/kWh", notifications[2].message)

                self.assertEqual(workflow.process_vehicle(samples[-1]), [])
                self.assertEqual(len(ledger.pending_notifications()), 3)
            finally:
                ledger.close()

    def test_reconciles_historical_telemetry_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                ledger.record_vehicle_observation(
                    observed_at=datetime(2026, 9, 11, 10, tzinfo=UTC),
                    soc_percent=Decimal("25"), odometer_miles=18900,
                )
                ledger.record_vehicle_observation(
                    observed_at=datetime(2026, 9, 11, 14, tzinfo=UTC),
                    soc_percent=Decimal("35"), odometer_miles=18900,
                )
                ledger.record_vehicle_observation(
                    observed_at=datetime(2026, 9, 12, 10, tzinfo=UTC),
                    soc_percent=Decimal("25"), odometer_miles=19000,
                )
                ledger.record_vehicle_observation(
                    observed_at=datetime(2026, 9, 12, 14, tzinfo=UTC),
                    soc_percent=Decimal("35"), odometer_miles=19000,
                )
                workflow = HomeChargingWorkflow(ledger, _Rates())

                self.assertEqual(
                    len(workflow.reconcile_away(start_at=datetime(2026, 9, 12, tzinfo=UTC))), 1
                )
                self.assertEqual(
                    workflow.reconcile_away(start_at=datetime(2026, 9, 12, tzinfo=UTC)), []
                )
                self.assertEqual(ledger.pending_notification_count(), 1)
            finally:
                ledger.close()

    def test_does_not_create_away_session_for_a_small_soc_change_or_home_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                workflow = HomeChargingWorkflow(ledger, _Rates())
                first = datetime(2026, 9, 12, 10, tzinfo=UTC)
                workflow.process_vehicle(_vehicle(first, "40", 19000))
                self.assertEqual(workflow.process_vehicle(_vehicle(first.replace(hour=11), "41", 19000)), [])

                ledger.record_zappi_observation(
                    observed_at=first.replace(hour=12), device_id="zappi-1", connected=True,
                    charging=True, power_kw=Decimal("7.2"), session_energy_kwh=Decimal("1"),
                )
                self.assertEqual(workflow.process_vehicle(_vehicle(first.replace(hour=13), "50", 19000)), [])
                self.assertEqual(ledger.pending_notification_count(), 0)
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
