import json
import unittest
from decimal import Decimal

from brontes.vw import CarConnectivityCliTelemetry


class VwTelemetryAdapterTests(unittest.TestCase):
    def test_reads_normalised_read_only_telemetry_from_carconnectivity_cli(self) -> None:
        calls: list[list[str]] = []
        vehicle = {
            "captured_at": {"val": "2026-09-01T12:00:00+00:00"},
            "odometer": {"val": 18742, "uni": "mi"},
            "drives": {"primary": {"level": {"val": 34, "uni": "%"}}},
            "charging": {
                "state": {"val": "charging"},
                "type": {"val": "dc"},
                "power": {"val": 72.5, "uni": "kW"},
            },
        }

        def run(command: list[str]) -> str:
            calls.append(command)
            if command[-1] == "list":
                return "/garage/WVGZZZ/captured_at\n"
            return json.dumps(vehicle)

        adapter = CarConnectivityCliTelemetry(
            executable="/opt/carconnectivity-cli",
            config_path="/etc/carconnectivity.json",
            token_path="/var/lib/brontes/vw.token",
            cache_path="/var/lib/brontes/vw.cache",
            run=run,
        )

        observation = adapter.read()

        self.assertEqual(observation.soc_percent, Decimal("34"))
        self.assertEqual(observation.odometer_miles, 18742)
        self.assertEqual(observation.charging_state, "charging")
        self.assertEqual(observation.charge_type, "dc")
        self.assertEqual(observation.charge_power_kw, Decimal("72.5"))
        self.assertEqual(observation.source_timestamp.isoformat(), "2026-09-01T12:00:00+00:00")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("vw_eu_data_act", "\n".join(" ".join(command) for command in calls))


if __name__ == "__main__":
    unittest.main()
