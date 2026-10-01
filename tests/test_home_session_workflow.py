import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from brontes.ledger import Ledger
from brontes.myenergi import ZappiTelemetry
from brontes.vw import VehicleTelemetry
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

                self.assertEqual(completed, [])
                self.assertEqual(ledger.pending_notification_count(), 0)

                completed = workflow.process_vehicle(
                    VehicleTelemetry(
                        source_timestamp=datetime(2026, 9, 1, 2, 31, tzinfo=UTC),
                        soc_percent=Decimal("80"),
                        odometer_miles=19050,
                        charging_state=None,
                        charge_type=None,
                        charge_power_kw=None,
                    )
                )

                self.assertEqual(len(completed), 1)
                self.assertEqual(ledger.pending_notification_count(), 1)
                callback = ledger.pending_notifications()[0].roadtrip_callback
                self.assertIn("odometer=19050", callback)
                self.assertIn("filled=1", callback)
            finally:
                ledger.close()

    def test_imports_reconciled_home_charge_without_a_notification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                started_at = datetime(2026, 9, 18, 8, 43, tzinfo=UTC)
                ended_at = datetime(2026, 9, 18, 9, 28, tzinfo=UTC)
                ledger.record_home_interval(
                    source_key="zappi:reconciled-test",
                    started_at=started_at,
                    ended_at=ended_at,
                    energy_kwh=Decimal("7.45"),
                )

                session = ledger.import_reconciled_charge(
                    source_key="roadtrip:2026-09-18:home:19461",
                    opened_at=started_at,
                    closed_at=ended_at,
                    odometer_miles=19461,
                    energy_kwh=Decimal("7.45"),
                    total_cost_gbp=Decimal("0.92"),
                    weighted_unit_price_p_per_kwh=Decimal("12.41"),
                    location_type="home",
                    energy_source="zappi_metered",
                    cost_source="agile_calculated",
                    assign_intervals_started_at=started_at,
                    assign_intervals_ended_at=ended_at,
                )

                self.assertIsNotNone(session)
                self.assertEqual(session.energy_kwh, Decimal("7.45"))
                self.assertEqual(ledger.pending_notification_count(), 0)
                self.assertEqual(
                    ledger._connection.execute(
                        "SELECT session_id FROM charging_intervals WHERE source_key = 'zappi:reconciled-test'"
                    ).fetchone()[0],
                    session.id,
                )
                self.assertIsNone(
                    ledger.import_reconciled_charge(
                        source_key="roadtrip:2026-09-18:home:19461",
                        opened_at=started_at,
                        closed_at=ended_at,
                        odometer_miles=19461,
                        energy_kwh=Decimal("7.45"),
                        total_cost_gbp=Decimal("0.92"),
                        weighted_unit_price_p_per_kwh=Decimal("12.41"),
                        location_type="home",
                        energy_source="zappi_metered",
                        cost_source="agile_calculated",
                        assign_intervals_started_at=started_at,
                        assign_intervals_ended_at=ended_at,
                    )
                )
            finally:
                ledger.close()

    def test_reconciles_an_existing_charge_to_an_authoritative_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / "brontes.sqlite3")
            try:
                session = ledger.import_reconciled_charge(
                    source_key="import:receipt-test",
                    opened_at=datetime(2026, 9, 13, 18, 21, tzinfo=UTC),
                    closed_at=datetime(2026, 9, 13, 18, 48, tzinfo=UTC),
                    odometer_miles=19321,
                    energy_kwh=Decimal("24.94"),
                    total_cost_gbp=Decimal("18.71"),
                    weighted_unit_price_p_per_kwh=Decimal("75.00"),
                    location_type="away",
                    energy_source="vw_soc_estimated",
                    cost_source="assumed_unit_price",
                )
                assert session is not None

                reconciled = ledger.reconcile_charge_from_receipt(
                    session_id=session.id,
                    energy_kwh=Decimal("29.9169"),
                    total_cost_gbp=Decimal("14.95"),
                    weighted_unit_price_p_per_kwh=Decimal("50.00"),
                    energy_source="tesla_supercharger_receipt",
                    cost_source="tesla_supercharger_receipt",
                    opened_at=datetime(2026, 9, 13, 18, 24, tzinfo=UTC),
                    closed_at=datetime(2026, 9, 13, 18, 36, tzinfo=UTC),
                )

                self.assertEqual(reconciled.energy_kwh, Decimal("29.9169"))
                self.assertEqual(reconciled.total_cost_gbp, Decimal("14.95"))
                self.assertEqual(reconciled.weighted_unit_price_p_per_kwh, Decimal("50.00"))
                self.assertEqual(reconciled.energy_source, "tesla_supercharger_receipt")
                self.assertEqual(ledger.pending_notification_count(), 0)
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
                completed = workflow.process_vehicle(
                    VehicleTelemetry(
                        source_timestamp=datetime(2026, 9, 1, 0, 31, tzinfo=UTC),
                        soc_percent=Decimal("80"),
                        odometer_miles=19044,
                        charging_state=None,
                        charge_type=None,
                        charge_power_kw=None,
                    )
                )

                self.assertEqual(len(completed), 1)
                self.assertEqual(completed[0].total_cost_gbp, Decimal("0.20"))
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
