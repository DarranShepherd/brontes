"""Command-line interface for Brontes operations."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol

from brontes.api import create_application
from brontes.config import Settings
from brontes.charge_control import ChargeController
from brontes.ledger import Ledger
from brontes.myenergi import MyEnergiZappiTelemetry, ZappiTelemetry
from brontes.myenergi_control import MyEnergiTimedBoosts
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
    on_vw_poll_failure: Callable[[datetime], object] | None = None,
    on_vw_poll_success: Callable[[datetime], object] | None = None,
) -> dict[str, object]:
    """Run one provider poll, then deliver any persisted notifications."""
    if provider == "zappi":
        sessions = workflow.process_zappi(zappi_reader(), observed_at)
    elif provider == "vw":
        try:
            sessions = workflow.process_vehicle(vehicle_reader())
        except Exception:
            if on_vw_poll_failure is not None:
                on_vw_poll_failure(observed_at)
            dispatcher.deliver_pending()
            raise
        if on_vw_poll_success is not None:
            on_vw_poll_success(observed_at)
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


def execute_manual_home_finalise(
    *,
    workflow: HomeChargingWorkflow,
    dispatcher: NotificationDispatcher,
    observed_at: datetime,
    soc_percent: Decimal,
    odometer_miles: int,
) -> dict[str, object]:
    """Finalise a pending home session from user-attested vehicle state."""
    sessions = workflow.finalise_manual_home(
        observed_at=observed_at,
        soc_percent=soc_percent,
        odometer_miles=odometer_miles,
    )
    return {
        "sessionsFinalised": len(sessions),
        "notificationsDelivered": dispatcher.deliver_pending(),
    }


def execute_reconcile_away(
    *, workflow: HomeChargingWorkflow, dispatcher: NotificationDispatcher
) -> dict[str, object]:
    """Backfill telemetry-derived away sessions and deliver their notifications."""
    sessions = workflow.reconcile_away()
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


def _charge_controller(ledger: Ledger) -> ChargeController:
    return ChargeController(
        ledger=ledger,
        rates=OctopusAgileRates(
            product_code=os.environ.get("BRONTES_OCTOPUS_PRODUCT_CODE", "AGILE-24-10-01"),
            tariff_code=os.environ.get("BRONTES_OCTOPUS_TARIFF_CODE", "E-1R-AGILE-24-10-01-B"),
        ),
        vehicle_reader=_vehicle_reader,
        writer=MyEnergiTimedBoosts(),
    )


def _plan_result(plan) -> dict[str, object]:
    return {
        "targetSocPercent": str(plan.target_soc_percent),
        "effectiveDeadline": plan.effective_deadline.isoformat(),
        "gridEnergyKwh": str(plan.grid_energy_kwh),
        "slots": [slot.isoformat() for slot in plan.slots],
    }


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
    manual_finalise = commands.add_parser(
        "manual-home-finalise",
        help="finalise a pending home session from user-attested vehicle state",
    )
    manual_finalise.add_argument("--soc-percent", required=True)
    manual_finalise.add_argument("--odometer-miles", required=True, type=int)
    commands.add_parser("reconcile-away", help="backfill away sessions from persisted VW telemetry")
    imported = commands.add_parser(
        "import-charge", help="import an already-reconciled charge without notification"
    )
    imported.add_argument("--source-key", required=True)
    imported.add_argument("--opened-at", required=True)
    imported.add_argument("--closed-at", required=True)
    imported.add_argument("--odometer-miles", required=True, type=int)
    imported.add_argument("--energy-kwh", required=True)
    imported.add_argument("--total-cost-gbp", required=True)
    imported.add_argument("--weighted-unit-price-p-per-kwh", required=True)
    imported.add_argument("--location-type", required=True, choices=("home", "away"))
    imported.add_argument("--energy-source", required=True)
    imported.add_argument("--cost-source", required=True)
    imported.add_argument("--assign-intervals-started-at")
    imported.add_argument("--assign-intervals-ended-at")
    receipt = commands.add_parser(
        "reconcile-receipt", help="replace an inferred charge with an authoritative receipt"
    )
    receipt.add_argument("--session-id", required=True, type=int)
    receipt.add_argument("--energy-kwh", required=True)
    receipt.add_argument("--total-cost-gbp", required=True)
    receipt.add_argument("--weighted-unit-price-p-per-kwh", required=True)
    receipt.add_argument("--energy-source", default="tesla_supercharger_receipt")
    receipt.add_argument("--cost-source", default="tesla_supercharger_receipt")
    receipt.add_argument("--opened-at")
    receipt.add_argument("--closed-at")
    charge = commands.add_parser("charge", help="schedule an explicitly requested home charge")
    charge.add_argument("--target-soc-percent", default="80")
    charge.add_argument("--deadline", help="timezone-aware ISO 8601 deadline")
    commands.add_parser("replan-charge", help="replan an active charge request when new prices are available")
    commands.add_parser("clear-due-charge", help="clear a completed Brontes-owned timed boost")
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
                on_vw_poll_failure=lambda observed_at: ledger.record_vw_poll_failure(
                    observed_at=observed_at
                ),
                on_vw_poll_success=lambda observed_at: ledger.record_vw_poll_success(
                    observed_at=observed_at
                ),
            )
        elif args.command == "reconcile":
            result = execute_reconcile(workflow=_workflow(ledger), dispatcher=_dispatcher(ledger))
        elif args.command == "manual-home-finalise":
            result = execute_manual_home_finalise(
                workflow=_workflow(ledger),
                dispatcher=_dispatcher(ledger),
                observed_at=datetime.now(timezone.utc),
                soc_percent=Decimal(args.soc_percent),
                odometer_miles=args.odometer_miles,
            )
        elif args.command == "reconcile-away":
            result = execute_reconcile_away(workflow=_workflow(ledger), dispatcher=_dispatcher(ledger))
        elif args.command == "charge":
            deadline = datetime.fromisoformat(args.deadline.replace("Z", "+00:00")) if args.deadline else None
            if deadline is not None and deadline.tzinfo is None:
                raise ValueError("charge deadline must include a timezone")
            result = _plan_result(
                _charge_controller(ledger).request(
                    now=datetime.now(timezone.utc),
                    target_soc_percent=Decimal(args.target_soc_percent),
                    deadline=deadline,
                )
            )
        elif args.command == "replan-charge":
            plan = _charge_controller(ledger).replan(now=datetime.now(timezone.utc))
            result = {"replanned": plan is not None, **(_plan_result(plan) if plan else {})}
        elif args.command == "clear-due-charge":
            result = {"cleared": _charge_controller(ledger).clear_if_due(now=datetime.now(timezone.utc))}
        elif args.command == "import-charge":
            session = ledger.import_reconciled_charge(
                source_key=args.source_key,
                opened_at=datetime.fromisoformat(args.opened_at.replace("Z", "+00:00")),
                closed_at=datetime.fromisoformat(args.closed_at.replace("Z", "+00:00")),
                odometer_miles=args.odometer_miles,
                energy_kwh=Decimal(args.energy_kwh),
                total_cost_gbp=Decimal(args.total_cost_gbp),
                weighted_unit_price_p_per_kwh=Decimal(args.weighted_unit_price_p_per_kwh),
                location_type=args.location_type,
                energy_source=args.energy_source,
                cost_source=args.cost_source,
                assign_intervals_started_at=(
                    datetime.fromisoformat(args.assign_intervals_started_at.replace("Z", "+00:00"))
                    if args.assign_intervals_started_at
                    else None
                ),
                assign_intervals_ended_at=(
                    datetime.fromisoformat(args.assign_intervals_ended_at.replace("Z", "+00:00"))
                    if args.assign_intervals_ended_at
                    else None
                ),
            )
            result = {"imported": session is not None, "sessionId": session.id if session else None}
        elif args.command == "reconcile-receipt":
            session = ledger.reconcile_charge_from_receipt(
                session_id=args.session_id,
                energy_kwh=Decimal(args.energy_kwh),
                total_cost_gbp=Decimal(args.total_cost_gbp),
                weighted_unit_price_p_per_kwh=Decimal(args.weighted_unit_price_p_per_kwh),
                energy_source=args.energy_source,
                cost_source=args.cost_source,
                opened_at=(
                    datetime.fromisoformat(args.opened_at.replace("Z", "+00:00"))
                    if args.opened_at else None
                ),
                closed_at=(
                    datetime.fromisoformat(args.closed_at.replace("Z", "+00:00"))
                    if args.closed_at else None
                ),
            )
            result = {"reconciled": True, "sessionId": session.id}
        else:
            result = _status(ledger)
        print(json.dumps(result, separators=(",", ":"), default=str))
        return 0
    finally:
        ledger.close()


if __name__ == "__main__":
    raise SystemExit(main())
