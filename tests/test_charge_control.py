import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from brontes.charge_control import ChargeController
from brontes.ledger import Ledger
from brontes.vw import VehicleTelemetry

UTC = timezone.utc


class ChargeControllerTests(unittest.TestCase):
    def test_request_persists_intent_and_uses_fresh_vehicle_soc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Ledger(Path(directory) / 'brontes.sqlite3')
            writes = []
            controller = ChargeController(
                ledger=ledger,
                rates=type('Rates', (), {'prices_between': lambda _, __, ___: {
                    datetime(2026, 10, 1, 12, tzinfo=UTC): Decimal('10'),
                    datetime(2026, 10, 1, 12, 30, tzinfo=UTC): Decimal('5'),
                }})(),
                vehicle_reader=lambda: VehicleTelemetry(datetime(2026, 10, 1, 11, 50, tzinfo=UTC), Decimal('70'), 20192, None, None, None),
                writer=type('Writer', (), {'replace': lambda _, slots, expected_current=(): writes.append((slots, expected_current))})(),
            )

            plan = controller.request(now=datetime(2026, 10, 1, 11, 45, tzinfo=UTC))

            self.assertEqual(plan.target_soc_percent, Decimal('80'))
            self.assertEqual(writes[0][1], ())
            self.assertEqual(ledger.charge_intent().planned_slots, plan.slots)
            ledger.close()


if __name__ == '__main__':
    unittest.main()
