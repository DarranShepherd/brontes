import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from pathlib import Path

from brontes.ledger import Ledger

UTC = timezone.utc


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 1, hour, minute, tzinfo=UTC)


class HomeChargingWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.temp_dir.name) / "brontes.sqlite3")

    def tearDown(self) -> None:
        self.ledger.close()
        self.temp_dir.cleanup()

    def test_odometer_change_reconciles_split_home_charge_and_queues_roadtrip(self) -> None:
        self.ledger.record_vehicle_observation(
            observed_at=at(0), soc_percent=Decimal("34"), odometer_miles=18742
        )
        self.ledger.record_home_interval(
            source_key="zappi-001",
            started_at=at(1),
            ended_at=at(1, 30),
            energy_kwh=Decimal("10.0"),
        )
        self.ledger.record_home_interval(
            source_key="zappi-002",
            started_at=at(2),
            ended_at=at(2, 30),
            energy_kwh=Decimal("14.8"),
        )
        self.ledger.record_agile_price(
            settlement_start=at(1), unit_price_p_per_kwh=Decimal("5")
        )
        self.ledger.record_agile_price(
            settlement_start=at(2), unit_price_p_per_kwh=Decimal("11.2837838")
        )

        sessions = self.ledger.reconcile_odometer_change(
            observed_at=at(8), odometer_miles=18750
        )

        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session.energy_kwh, Decimal("24.8"))
        self.assertEqual(session.total_cost_gbp, Decimal("2.17"))
        self.assertEqual(session.weighted_unit_price_p_per_kwh, Decimal("8.75"))
        self.assertEqual(session.location_type, "home")
        self.assertEqual(session.energy_source, "zappi_metered")
        self.assertEqual(session.cost_source, "agile_calculated")

        pending = self.ledger.pending_notifications()
        self.assertEqual(len(pending), 1)
        self.assertIn("roadtrip://x-callback-url/addFuel?", pending[0].roadtrip_callback)
        self.assertIn("24.8 kWh", pending[0].message)
        self.assertIn("£2.17", pending[0].message)
        self.assertIn(
            f'<a href="{escape(pending[0].roadtrip_callback, quote=True)}">Add to Road Trip</a>',
            pending[0].message,
        )

    def test_repeated_zappi_interval_source_key_does_not_double_count(self) -> None:
        self.ledger.record_home_interval(
            source_key="zappi-001",
            started_at=at(1),
            ended_at=at(1, 30),
            energy_kwh=Decimal("10.0"),
        )
        self.ledger.record_home_interval(
            source_key="zappi-001",
            started_at=at(1),
            ended_at=at(1, 30),
            energy_kwh=Decimal("10.0"),
        )
        self.ledger.record_agile_price(
            settlement_start=at(1), unit_price_p_per_kwh=Decimal("5")
        )

        sessions = self.ledger.reconcile_odometer_change(
            observed_at=at(8), odometer_miles=18750
        )

        self.assertEqual(sessions[0].energy_kwh, Decimal("10.0"))
        self.assertEqual(sessions[0].total_cost_gbp, Decimal("0.50"))


if __name__ == "__main__":
    unittest.main()
