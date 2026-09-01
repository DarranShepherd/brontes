import unittest
from decimal import Decimal

from brontes.myenergi import MyEnergiZappiTelemetry


class MyEnergiZappiTelemetryTests(unittest.TestCase):
    def test_reads_connected_and_charging_zappi_state(self) -> None:
        adapter = MyEnergiZappiTelemetry(
            fetch=lambda: {
                "zappi": [
                    {"sno": 12345678, "pst": "C2", "sta": 3, "div": 7200, "che": 12.34}
                ]
            }
        )

        observation = adapter.read()

        self.assertEqual(observation.device_id, "12345678")
        self.assertTrue(observation.connected)
        self.assertTrue(observation.charging)
        self.assertEqual(observation.power_kw, Decimal("7.2"))
        self.assertEqual(observation.session_energy_kwh, Decimal("12.34"))

    def test_reports_connected_but_not_charging_state(self) -> None:
        observation = MyEnergiZappiTelemetry(
            fetch=lambda: {"zappi": [{"sno": 12345678, "pst": "B1", "sta": 1, "div": 0, "che": 0.03}]}
        ).read()

        self.assertTrue(observation.connected)
        self.assertFalse(observation.charging)
        self.assertEqual(observation.power_kw, Decimal("0"))


if __name__ == "__main__":
    unittest.main()
