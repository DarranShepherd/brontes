import unittest
from decimal import Decimal

from brontes.roadtrip import create_charge_callback


class RoadTripCallbackTests(unittest.TestCase):
    def test_generates_charge_callback_with_authoritative_values(self) -> None:
        callback = create_charge_callback(
            energy_kwh=Decimal("24.8"),
            total_cost_gbp=Decimal("2.17"),
            timestamp="2026-09-01T06:45:00Z",
            odometer_miles=18742,
            notes="Home · Zappi · Agile",
        )

        self.assertEqual(
            callback,
            "roadtrip://x-callback-url/addFuel?"
            "amount=24.8&cost=2.17&date=2026-09-01T06%3A45%3A00Z&"
            "odometer=18742&notes=Home+%C2%B7+Zappi+%C2%B7+Agile",
        )


if __name__ == "__main__":
    unittest.main()
