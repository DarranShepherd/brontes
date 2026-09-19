import sqlite3
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
    def test_migrates_existing_away_charge_tracking_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "brontes.sqlite3"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute("""CREATE TABLE away_charge_tracking (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    baseline_at TEXT NOT NULL,
                    baseline_soc_percent TEXT NOT NULL,
                    baseline_odometer_miles INTEGER NOT NULL,
                    last_observed_at TEXT NOT NULL,
                    last_soc_percent TEXT NOT NULL,
                    last_odometer_miles INTEGER NOT NULL,
                    charge_opened_at TEXT,
                    charge_start_soc_percent TEXT,
                    charge_start_odometer_miles INTEGER
                )""")
                connection.commit()
            finally:
                connection.close()

            ledger = Ledger(database_path)
            try:
                columns = {row[1] for row in ledger._connection.execute("PRAGMA table_info(away_charge_tracking)")}
                self.assertIn("positive_soc_rises", columns)
            finally:
                ledger.close()

    def test_creates_ac_and_dc_away_sessions_from_confirmed_soc_rises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                workflow = HomeChargingWorkflow(ledger, _Rates())
                samples = [
                    _vehicle(datetime(2026, 9, 12, 10, 36, tzinfo=UTC), "27", 19285),
                    _vehicle(datetime(2026, 9, 12, 12, 30, tzinfo=UTC), "31", 19285),
                    _vehicle(datetime(2026, 9, 12, 14, 57, tzinfo=UTC), "36", 19285),
                    _vehicle(datetime(2026, 9, 13, 10, 29, tzinfo=UTC), "25", 19306),
                    _vehicle(datetime(2026, 9, 13, 10, 55, tzinfo=UTC), "30", 19306),
                    _vehicle(datetime(2026, 9, 13, 11, 25, tzinfo=UTC), "36", 19306),
                    _vehicle(datetime(2026, 9, 13, 18, 21, tzinfo=UTC), "26", 19312),
                    _vehicle(datetime(2026, 9, 13, 18, 35, tzinfo=UTC), "40", 19312),
                    _vehicle(datetime(2026, 9, 13, 18, 48, tzinfo=UTC), "55", 19312),
                    _vehicle(datetime(2026, 9, 13, 19, 48, tzinfo=UTC), "55", 19321),
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

    def test_ignores_stationary_regressive_soc_before_a_repeated_value(self) -> None:
        """A stale VW response must not turn a prior SoC into a phantom charge."""
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                workflow = HomeChargingWorkflow(ledger, _Rates())
                samples = [
                    _vehicle(datetime(2026, 9, 18, 16, 48, tzinfo=UTC), "35", 19614),
                    _vehicle(datetime(2026, 9, 18, 16, 55, tzinfo=UTC), "26", 19614),
                    _vehicle(datetime(2026, 9, 18, 17, 12, tzinfo=UTC), "35", 19614),
                ]

                completed = []
                for sample in samples:
                    completed.extend(workflow.process_vehicle(sample))

                self.assertEqual(completed, [])
                self.assertEqual(ledger.pending_notification_count(), 0)
            finally:
                ledger.close()

    def test_ignores_stale_soc_across_a_short_drive(self) -> None:
        """A stale reading must remain rejected when it survives into a later odometer value."""
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                workflow = HomeChargingWorkflow(ledger, _Rates())
                samples = [
                    _vehicle(datetime(2026, 9, 18, 16, 48, tzinfo=UTC), "35", 19603),
                    _vehicle(datetime(2026, 9, 18, 16, 55, tzinfo=UTC), "26", 19603),
                    _vehicle(datetime(2026, 9, 18, 17, 58, tzinfo=UTC), "26", 19614),
                    _vehicle(datetime(2026, 9, 18, 18, 12, tzinfo=UTC), "35", 19614),
                    _vehicle(datetime(2026, 9, 18, 18, 34, tzinfo=UTC), "35", 19614),
                    _vehicle(datetime(2026, 9, 18, 19, 34, tzinfo=UTC), "35", 19614),
                ]

                completed = []
                for sample in samples:
                    completed.extend(workflow.process_vehicle(sample))

                self.assertEqual(completed, [])
                self.assertEqual(ledger.pending_notification_count(), 0)
            finally:
                ledger.close()

    def test_combines_one_away_charge_and_notifies_only_after_a_plateau(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                workflow = HomeChargingWorkflow(ledger, _Rates())
                started_at = datetime(2026, 9, 19, 1, tzinfo=UTC)
                charging_samples = [
                    _vehicle(started_at, "35", 19614),
                    _vehicle(started_at.replace(hour=1, minute=30), "38", 19614),
                    _vehicle(started_at.replace(hour=2), "41", 19614),
                    _vehicle(started_at.replace(hour=3), "45", 19614),
                    _vehicle(started_at.replace(hour=4), "50", 19614),
                ]
                for sample in charging_samples:
                    self.assertEqual(workflow.process_vehicle(sample), [])
                self.assertEqual(ledger.pending_notification_count(), 0)

                completed = workflow.process_vehicle(
                    _vehicle(started_at.replace(hour=5), "50", 19614)
                )

                self.assertEqual(len(completed), 1)
                self.assertEqual(completed[0].energy_kwh, Decimal("12.90"))
                notifications = ledger.pending_notifications()
                self.assertEqual(len(notifications), 1)
                self.assertIn("VW SoC: 35% → 50%", notifications[0].message)
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
                    observed_at=datetime(2026, 9, 12, 12, tzinfo=UTC),
                    soc_percent=Decimal("30"), odometer_miles=19000,
                )
                ledger.record_vehicle_observation(
                    observed_at=datetime(2026, 9, 12, 14, tzinfo=UTC),
                    soc_percent=Decimal("35"), odometer_miles=19000,
                )
                ledger.record_vehicle_observation(
                    observed_at=datetime(2026, 9, 12, 15, tzinfo=UTC),
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

    def test_does_not_create_away_session_when_zappi_starts_charging_just_after_vw_snapshot(self) -> None:
        """VW's source timestamp can precede the Zappi poll that confirms home charging."""
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                workflow = HomeChargingWorkflow(ledger, _Rates())
                previous = datetime(2026, 9, 14, 21, 49, 26, tzinfo=UTC)
                vw_snapshot = datetime(2026, 9, 15, 10, 42, 38, tzinfo=UTC)
                workflow.process_vehicle(_vehicle(previous, "6", 19433))
                ledger.record_zappi_observation(
                    observed_at=datetime(2026, 9, 15, 10, 45, 45, tzinfo=UTC),
                    device_id="22307745",
                    connected=True,
                    charging=True,
                    power_kw=Decimal("11.334"),
                    session_energy_kwh=Decimal("0.58"),
                )

                self.assertEqual(
                    workflow.process_vehicle(_vehicle(vw_snapshot, "26", 19433)), []
                )
                self.assertEqual(ledger.pending_notification_count(), 0)
            finally:
                ledger.close()

    def test_does_not_create_away_session_when_zappi_was_connected_just_before_vw_interval(self) -> None:
        """A Zappi poll immediately before VW's interval still proves this was home charging."""
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                workflow = HomeChargingWorkflow(ledger, _Rates())
                zappi_observed_at = datetime(2026, 9, 17, 15, 1, 11, tzinfo=UTC)
                previous = datetime(2026, 9, 17, 15, 1, 54, tzinfo=UTC)
                current = datetime(2026, 9, 17, 15, 2, 15, tzinfo=UTC)
                ledger.record_zappi_observation(
                    observed_at=zappi_observed_at,
                    device_id="22307745",
                    connected=True,
                    charging=False,
                    power_kw=Decimal("0"),
                    session_energy_kwh=Decimal("56.82"),
                )
                workflow.process_vehicle(_vehicle(previous, "26", 19454))

                self.assertEqual(workflow.process_vehicle(_vehicle(current, "80", 19454)), [])
                self.assertEqual(ledger.pending_notification_count(), 0)
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
