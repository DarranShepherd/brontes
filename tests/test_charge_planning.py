import unittest
from datetime import datetime, timezone
from decimal import Decimal

from brontes.charge_planning import ChargePlanner

UTC = timezone.utc


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 1, hour, minute, tzinfo=UTC)


class ChargePlannerTests(unittest.TestCase):
    def test_defaults_to_80_percent_and_uses_the_full_published_price_horizon(self) -> None:
        planner = ChargePlanner(battery_kwh=Decimal("79"), power_kw=Decimal("11"), efficiency=Decimal("0.90"))
        prices = {
            at(12): Decimal("30"),
            at(12, 30): Decimal("10"),
            at(13): Decimal("20"),
            at(13, 30): Decimal("5"),
        }

        plan = planner.plan(
            current_soc_percent=Decimal("70"),
            prices=prices,
            now=at(11, 45),
        )

        self.assertEqual(plan.target_soc_percent, Decimal("80"))
        self.assertEqual(plan.effective_deadline, at(14))
        self.assertEqual(plan.slots, (at(12, 30), at(13, 30)))
        self.assertEqual(plan.grid_energy_kwh, Decimal("8.777777777777777777777777778"))
    def test_deadline_beyond_published_prices_uses_only_the_available_horizon(self) -> None:
        planner = ChargePlanner(battery_kwh=Decimal("86"), power_kw=Decimal("11"), efficiency=Decimal("0.90"))
        prices = {at(12): Decimal("10"), at(12, 30): Decimal("5"), at(13): Decimal("20")}

        plan = planner.plan(
            current_soc_percent=Decimal("80"), prices=prices, now=at(11, 45),
            target_soc_percent=Decimal("90"), requested_deadline=at(19),
        )

        self.assertEqual(plan.effective_deadline, at(13, 30))
        self.assertEqual(plan.slots, (at(12), at(12, 30)))
        self.assertEqual(plan.grid_energy_kwh, Decimal("9.555555555555555555555555556"))


if __name__ == "__main__":
    unittest.main()
