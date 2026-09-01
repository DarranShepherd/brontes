import unittest
from datetime import datetime, timezone
from decimal import Decimal

from brontes.octopus import OctopusAgileRates


class OctopusAgileRatesTests(unittest.TestCase):
    def test_reads_vat_inclusive_settlement_prices(self) -> None:
        requested_urls = []
        adapter = OctopusAgileRates(
            product_code="AGILE-24-10-01",
            tariff_code="E-1R-AGILE-24-10-01-B",
            fetch=lambda url: requested_urls.append(url) or {
                "results": [
                    {"valid_from": "2026-09-01T00:00:00Z", "value_inc_vat": "8.5"},
                    {"valid_from": "2026-09-01T00:30:00Z", "value_inc_vat": "9.1"},
                ]
            },
        )

        prices = adapter.prices_between(
            datetime(2026, 9, 1, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 1, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(prices[datetime(2026, 9, 1, 0, tzinfo=timezone.utc)], Decimal("8.5"))
        self.assertEqual(prices[datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc)], Decimal("9.1"))
        self.assertIn("period_from=2026-09-01T00%3A00%3A00Z", requested_urls[0])


if __name__ == "__main__":
    unittest.main()
