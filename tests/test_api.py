import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from brontes.api import create_application
from brontes.ledger import Ledger

UTC = timezone.utc


class LocalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.temp_dir.name) / "brontes.sqlite3")
        self.application = create_application(self.ledger)

    def tearDown(self) -> None:
        self.ledger.close()
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, payload: dict[str, object] | None = None) -> tuple[str, dict[str, object]]:
        environ: dict[str, object] = {}
        setup_testing_defaults(environ)
        environ["REQUEST_METHOD"] = method
        environ["PATH_INFO"] = path
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        environ["CONTENT_LENGTH"] = str(len(body))
        environ["wsgi.input"] = io.BytesIO(body)
        status: list[str] = []

        response = self.application(environ, lambda value, _headers: status.append(value))

        return status[0], json.loads(b"".join(response))

    def test_accepts_home_energy_and_reconciles_a_costed_session(self) -> None:
        status, health = self.request("GET", "/health")
        self.assertEqual(status, "200 OK")
        self.assertEqual(health["service"], "brontes")

        status, _ = self.request(
            "POST",
            "/observations/zappi",
            {
                "sourceKey": "zappi-001",
                "startedAt": "2026-09-01T01:00:00Z",
                "endedAt": "2026-09-01T01:30:00Z",
                "energyKwh": "10",
            },
        )
        self.assertEqual(status, "201 Created")
        status, _ = self.request(
            "POST",
            "/prices/agile",
            {"settlementStart": "2026-09-01T01:00:00Z", "unitPricePPerKwh": "5"},
        )
        self.assertEqual(status, "201 Created")

        status, reconciliation = self.request(
            "POST",
            "/reconcile/odometer",
            {"observedAt": "2026-09-01T08:00:00Z", "odometerMiles": 18750},
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(reconciliation["sessions"][0]["totalCostGbp"], "0.50")
        status, current_status = self.request("GET", "/status")
        self.assertEqual(status, "200 OK")
        self.assertEqual(current_status["pendingNotifications"], 1)


if __name__ == "__main__":
    unittest.main()
