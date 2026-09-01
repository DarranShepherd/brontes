"""Command-line interface for Brontes operations."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from brontes.api import create_application
from brontes.config import Settings
from brontes.ledger import Ledger
from brontes.myenergi import MyEnergiZappiTelemetry, ZappiTelemetry
from brontes.notifications import HermesCliNotificationDispatcher, HermesNotificationDispatcher
from brontes.octopus import OctopusAgileRates
from brontes.vw import CarConnectivityCliTelemetry, VehicleTelemetry
from brontes.workflow import HomeChargingWorkflow


class NotificationDispatcher(Protocol):
    def deliver_pending(self) -> int: ...


def execute_poll(
    provider: str,
    *,
    workflow: HomeChargingWorkflow,
    zappi_reader: Callable[[], ZappiTelemetry],
    vehicle_reader: Callable[[], VehicleTelemetry],
    dispatcher: NotificationDispatcher,
    observed_at: datetime,
) -> dict[str, object]:
    """Run one provider poll, then deliver any persisted notifications."""
    if provider == "zappi":
        sessions = workflow.process_zappi(zappi_reader(), observed_at)
    elif provider == "vw":
        sessions = workflow.process_vehicle(vehicle_reader())
    else:
        raise ValueError(f"unsupported provider: {provider}")
    return {
        "provider": provider,
        "sessionsFinalised": len(sessions),
        "notificationsDelivered": dispatcher.deliver_pending(),
    }


def execute_reconcile(
    *, workflow: HomeChargingWorkflow, dispatcher: NotificationDispatcher
) -> dict[str, object]:
    """Retry a persisted, pending home-session finalisation and notifications."""
    sessions = workflow.reconcile_pending()
    return {
        "sessionsFinalised": len(sessions),
        "notificationsDelivered": dispatcher.deliver_pending(),
    }


def _database_path() -> Path:
    return Path(os.environ.get("BRONTES_DATABASE_PATH", "data/brontes.sqlite3"))


def _workflow(ledger: Ledger) -> HomeChargingWorkflow:
    return HomeChargingWorkflow(
        ledger,
        OctopusAgileRates(
            product_code=os.environ.get("BRONTES_OCTOPUS_PRODUCT_CODE", "AGILE-24-10-01"),
            tariff_code=os.environ.get("BRONTES_OCTOPUS_TARIFF_CODE", "E-1R-AGILE-24-10-01-B"),
        ),
    )


def _vehicle_reader() -> VehicleTelemetry:
    return CarConnectivityCliTelemetry(
        executable=os.environ.get(
            "BRONTES_CARCONNECTIVITY_CLI",
            "/home/hermes/workspace/projects/CarConnectivity/.venv-eu-data-act/bin/carconnectivity-cli",
        ),
        config_path=os.environ.get(
            "BRONTES_CARCONNECTIVITY_CONFIG",
            "/home/hermes/workspace/projects/carconnectivity-vw/carconnectivity.eu-data-act.json",
        ),
        token_path=os.environ.get(
            "BRONTES_CARCONNECTIVITY_TOKEN",
            "/home/hermes/workspace/scratch/carconnectivity/eu-data-act.token",
        ),
        cache_path=os.environ.get(
            "BRONTES_CARCONNECTIVITY_CACHE",
            "/home/hermes/workspace/scratch/carconnectivity/eu-data-act.cache",
        ),
    ).read()


def _zappi_reader() -> ZappiTelemetry:
    return MyEnergiZappiTelemetry().read()


def _dispatcher(ledger: Ledger) -> HermesCliNotificationDispatcher:
    return HermesCliNotificationDispatcher(
        ledger,
        target=os.environ.get("BRONTES_TELEGRAM_TARGET", "telegram"),
    )


def _status(ledger: Ledger) -> dict[str, object]:
    return {
        "pendingNotifications": ledger.pending_notification_count(),
        "zappi": ledger.latest_zappi_state(),
        "lastOdometerMiles": ledger.latest_vehicle_odometer(),
        "homeSessionClosurePending": ledger.requested_home_session_closure() is not None,
    }


def _serve() -> None:
    settings = Settings.from_environment()
    ledger = Ledger(settings.database_path)
    dispatcher = (
        HermesNotificationDispatcher(ledger, settings.hermes_notification_url)
        if settings.hermes_notification_url
        else None
    )
    from wsgiref.simple_server import make_server

    application = create_application(ledger, dispatcher)
    with make_server(settings.host, settings.port, application) as server:
        print(f"Brontes listening on http://{settings.host}:{settings.port}")
        server.serve_forever()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brontes")
    commands = parser.add_subparsers(dest="command", required=True)

    poll = commands.add_parser("poll", help="poll one read-only provider")
    poll.add_argument("provider", choices=("zappi", "vw"))
    commands.add_parser("reconcile", help="retry pending session finalisation and delivery")
    commands.add_parser("status", help="print persisted local status")
    commands.add_parser("serve", help="run the optional loopback HTTP API")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        _serve()
        return 0

    ledger = Ledger(_database_path())
    try:
        if args.command == "poll":
            result = execute_poll(
                args.provider,
                workflow=_workflow(ledger),
                zappi_reader=_zappi_reader,
                vehicle_reader=_vehicle_reader,
                dispatcher=_dispatcher(ledger),
                observed_at=datetime.now(timezone.utc),
            )
        elif args.command == "reconcile":
            result = execute_reconcile(workflow=_workflow(ledger), dispatcher=_dispatcher(ledger))
        else:
            result = _status(ledger)
        print(json.dumps(result, separators=(",", ":"), default=str))
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
