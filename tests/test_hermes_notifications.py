import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from brontes.ledger import Ledger
from brontes.notifications import HermesNotificationDispatcher

UTC = timezone.utc


class _CaptureHandler(BaseHTTPRequestHandler):
    payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers["Content-Length"])
        self.payloads.append(json.loads(self.rfile.read(content_length)))
        self.send_response(202)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


class HermesNotificationDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        _CaptureHandler.payloads = []
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.temp_dir.name) / "brontes.sqlite3")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.ledger.close()
        self.temp_dir.cleanup()

    def test_posts_persisted_roadtrip_message_to_default_hermes_profile(self) -> None:
        self.ledger.record_home_interval(
            source_key="zappi-001",
            started_at=datetime(2026, 9, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 9, 1, 1, 30, tzinfo=UTC),
            energy_kwh=Decimal("10"),
        )
        self.ledger.record_agile_price(
            settlement_start=datetime(2026, 9, 1, 1, tzinfo=UTC),
            unit_price_p_per_kwh=Decimal("5"),
        )
        self.ledger.reconcile_odometer_change(
            observed_at=datetime(2026, 9, 1, 8, tzinfo=UTC), odometer_miles=18750
        )
        dispatcher = HermesNotificationDispatcher(
            self.ledger, f"http://127.0.0.1:{self.server.server_port}/events"
        )

        delivered = dispatcher.deliver_pending()

        self.assertEqual(delivered, 1)
        self.assertEqual(self.ledger.pending_notifications(), [])
        self.assertEqual(len(_CaptureHandler.payloads), 1)
        self.assertEqual(_CaptureHandler.payloads[0]["target_profile"], "default")
        self.assertIn("Buzz charge complete", _CaptureHandler.payloads[0]["text"])
        self.assertIn("roadtrip://x-callback-url", _CaptureHandler.payloads[0]["roadtrip_callback"])


if __name__ == "__main__":
    unittest.main()
