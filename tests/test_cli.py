import unittest
from datetime import datetime, timezone
from decimal import Decimal

from brontes.cli import execute_poll, execute_reconcile
from brontes.myenergi import ZappiTelemetry
from brontes.vw import VehicleTelemetry


class _Workflow:
    def __init__(self) -> None:
        self.events = []

    def process_zappi(self, observation, observed_at):
        self.events.append(("zappi", observation, observed_at))
        return ["session"]

    def process_vehicle(self, observation):
        self.events.append(("vw", observation))
        return []

    def reconcile_pending(self):
        self.events.append(("reconcile",))
        return ["session"]


class _Dispatcher:
    def __init__(self) -> None:
        self.calls = 0

    def deliver_pending(self):
        self.calls += 1
        return 2


class CliCommandTests(unittest.TestCase):
    def test_zappi_poll_processes_telemetry_and_delivers_pending_notifications(self) -> None:
        workflow = _Workflow()
        dispatcher = _Dispatcher()
        observation = ZappiTelemetry("zappi", True, True, Decimal("7.2"), Decimal("1.2"))
        when = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)

        result = execute_poll(
            "zappi",
            workflow=workflow,
            zappi_reader=lambda: observation,
            vehicle_reader=lambda: self.fail("unexpected VW read"),
            dispatcher=dispatcher,
            observed_at=when,
        )

        self.assertEqual(result, {"provider": "zappi", "sessionsFinalised": 1, "notificationsDelivered": 2})
        self.assertEqual(workflow.events, [("zappi", observation, when)])
        self.assertEqual(dispatcher.calls, 1)

    def test_reconcile_retries_pending_finalisation_and_notifications(self) -> None:
        workflow = _Workflow()
        dispatcher = _Dispatcher()

        result = execute_reconcile(workflow=workflow, dispatcher=dispatcher)

        self.assertEqual(result, {"sessionsFinalised": 1, "notificationsDelivered": 2})
        self.assertEqual(workflow.events, [("reconcile",)])
        self.assertEqual(dispatcher.calls, 1)

    def test_vw_poll_processes_vehicle_without_using_local_clock(self) -> None:
        workflow = _Workflow()
        dispatcher = _Dispatcher()
        observation = VehicleTelemetry(
            source_timestamp=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
            soc_percent=Decimal("50"), odometer_miles=19044,
            charging_state=None, charge_type=None, charge_power_kw=None,
        )

        result = execute_poll(
            "vw",
            workflow=workflow,
            zappi_reader=lambda: self.fail("unexpected Zappi read"),
            vehicle_reader=lambda: observation,
            dispatcher=dispatcher,
            observed_at=datetime(2026, 9, 1, 12, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(result, {"provider": "vw", "sessionsFinalised": 0, "notificationsDelivered": 2})
        self.assertEqual(workflow.events, [("vw", observation)])


if __name__ == "__main__":
    unittest.main()
