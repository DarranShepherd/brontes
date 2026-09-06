import unittest
from decimal import Decimal

from brontes.roadtrip import create_charge_callback, create_handoff_url


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
            "desroadtrip://x-callback-url/addFuel?"
            "vehicle=Volkswagen%20ID.Buzz%20GTX&fillAmount=24.8&cost=2.17&date=2026-09-01%2007%3A45&"
            "odometer=18742&notes=Home%20%C2%B7%20Zappi%20%C2%B7%20Agile",
        )

    def test_generates_explicit_unit_price_and_unfilled_state(self) -> None:
        callback = create_charge_callback(
            energy_kwh=Decimal("20.95"),
            total_cost_gbp=Decimal("-0.51"),
            unit_price_p_per_kwh=Decimal("-2.423333005686773975440960861"),
            filled=False,
            timestamp="2026-09-04T12:57:48Z",
            odometer_miles=19073,
            notes="Home · Zappi · Agile",
        )

        self.assertIn("unitPrice=-2.423333005686773975440960861", callback)
        self.assertIn("filled=0", callback)
        self.assertIn("date=2026-09-04%2013%3A57", callback)

    def test_handoff_url_keeps_callback_out_of_the_https_request(self) -> None:
        callback = "desroadtrip://x-callback-url/addFuel?fillAmount=24.8&cost=2.17"

        handoff = create_handoff_url(
            callback,
            handoff_page_url="https://darranshepherd.github.io/brontes/roadtrip/",
        )

        self.assertTrue(handoff.startswith("https://darranshepherd.github.io/brontes/roadtrip/#"))
        self.assertNotIn("desroadtrip", handoff.removesuffix(handoff.split("#", 1)[1]))
        self.assertNotIn("fillAmount", handoff.removesuffix(handoff.split("#", 1)[1]))


if __name__ == "__main__":
    unittest.main()
