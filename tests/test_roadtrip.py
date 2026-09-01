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
