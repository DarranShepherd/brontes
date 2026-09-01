"""Loopback HTTP/JSON API for Hermes and read-only adapters."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Callable

from brontes.ledger import Ledger

StartResponse = Callable[[str, list[tuple[str, str]]], None]


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return timestamp


def _json_response(start_response: StartResponse, status: str, payload: dict[str, object]) -> list[bytes]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


def create_application(ledger: Ledger):
    """Create a WSGI app without exposing the database or credentials."""

    def application(environ: dict[str, object], start_response: StartResponse) -> list[bytes]:
        method = str(environ["REQUEST_METHOD"])
        path = str(environ["PATH_INFO"])
        if method == "GET" and path == "/health":
            return _json_response(
                start_response,
                "200 OK",
                {"service": "brontes", "status": "ok", "notificationDeliveryConfigured": False},
            )
        if method == "GET" and path == "/status":
            return _json_response(
                start_response,
                "200 OK",
                {"pendingNotifications": ledger.pending_notification_count()},
            )
        if method != "POST":
            return _json_response(start_response, "404 Not Found", {"error": "not found"})
        try:
            content_length = int(str(environ.get("CONTENT_LENGTH") or "0"))
            stream = environ["wsgi.input"]
            payload = json.loads(stream.read(content_length))  # type: ignore[union-attr]
            if path == "/observations/zappi":
                ledger.record_home_interval(
                    source_key=str(payload["sourceKey"]),
                    started_at=_parse_timestamp(str(payload["startedAt"])),
                    ended_at=_parse_timestamp(str(payload["endedAt"])),
                    energy_kwh=Decimal(str(payload["energyKwh"])),
                )
                return _json_response(start_response, "201 Created", {"status": "recorded"})
            if path == "/prices/agile":
                ledger.record_agile_price(
                    settlement_start=_parse_timestamp(str(payload["settlementStart"])),
                    unit_price_p_per_kwh=Decimal(str(payload["unitPricePPerKwh"])),
                )
                return _json_response(start_response, "201 Created", {"status": "recorded"})
            if path == "/reconcile/odometer":
                sessions = ledger.reconcile_odometer_change(
                    observed_at=_parse_timestamp(str(payload["observedAt"])),
                    odometer_miles=int(payload["odometerMiles"]),
                )
                return _json_response(
                    start_response,
                    "200 OK",
                    {
                        "sessions": [
                            {
                                "id": session.id,
                                "totalEnergyKwh": str(session.energy_kwh),
                                "totalCostGbp": str(session.total_cost_gbp),
                            }
                            for session in sessions
                        ]
                    },
                )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            return _json_response(start_response, "400 Bad Request", {"error": str(error)})
        return _json_response(start_response, "404 Not Found", {"error": "not found"})

    return application
