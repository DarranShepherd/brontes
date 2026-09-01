"""SQLite-backed charging ledger for deterministic read-only workflows."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from brontes.roadtrip import (
    DEFAULT_HANDOFF_PAGE_URL,
    create_charge_callback,
    create_handoff_url,
)

UTC = timezone.utc
MONEY = Decimal("0.01")
PRICE = Decimal("0.01")


@dataclass(frozen=True)
class ChargingSession:
    id: int
    energy_kwh: Decimal
    total_cost_gbp: Decimal
    weighted_unit_price_p_per_kwh: Decimal
    location_type: str
    energy_source: str
    cost_source: str


@dataclass(frozen=True)
class PendingNotification:
    id: int
    session_id: int
    message: str
    roadtrip_callback: str


@dataclass(frozen=True)
class ZappiObservation:
    observed_at: datetime
    device_id: str
    connected: bool
    charging: bool
    power_kw: Decimal
    session_energy_kwh: Decimal | None


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _decimal(value: str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(value)


class Ledger:
    """Persist observations before deriving costed charging sessions."""

    def __init__(
        self,
        database_path: Path,
        *,
        roadtrip_handoff_page_url: str = DEFAULT_HANDOFF_PAGE_URL,
    ) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._roadtrip_handoff_page_url = roadtrip_handoff_page_url
        self._connection = sqlite3.connect(database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS vehicle_observations (
                id INTEGER PRIMARY KEY,
                observed_at TEXT NOT NULL UNIQUE,
                soc_percent TEXT NOT NULL,
                odometer_miles INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT 'vw_eu_data_act'
            );
            CREATE TABLE IF NOT EXISTS charging_intervals (
                id INTEGER PRIMARY KEY,
                source_key TEXT NOT NULL UNIQUE,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                energy_kwh TEXT NOT NULL,
                location_type TEXT NOT NULL,
                energy_source TEXT NOT NULL,
                session_id INTEGER REFERENCES charging_sessions(id)
            );
            CREATE TABLE IF NOT EXISTS agile_prices (
                settlement_start TEXT PRIMARY KEY,
                unit_price_p_per_kwh TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS zappi_observations (
                id INTEGER PRIMARY KEY,
                observed_at TEXT NOT NULL,
                device_id TEXT NOT NULL,
                connected INTEGER NOT NULL,
                charging INTEGER NOT NULL,
                power_kw TEXT NOT NULL,
                session_energy_kwh TEXT
            );
            CREATE TABLE IF NOT EXISTS charging_sessions (
                id INTEGER PRIMARY KEY,
                opened_at TEXT NOT NULL,
                closed_at TEXT NOT NULL,
                odometer_miles INTEGER NOT NULL,
                location_type TEXT NOT NULL,
                total_energy_kwh TEXT NOT NULL,
                total_cost_gbp TEXT NOT NULL,
                weighted_unit_price_p_per_kwh TEXT NOT NULL,
                energy_source TEXT NOT NULL,
                cost_source TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL UNIQUE REFERENCES charging_sessions(id),
                message TEXT NOT NULL,
                roadtrip_callback TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                delivered_at TEXT
            );
            CREATE TABLE IF NOT EXISTS home_session_closure (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                requested_at TEXT NOT NULL,
                odometer_miles INTEGER NOT NULL
            );
            """
        )
        self._connection.commit()

    def record_vehicle_observation(
        self, *, observed_at: datetime, soc_percent: Decimal, odometer_miles: int
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO vehicle_observations(observed_at, soc_percent, odometer_miles)
            VALUES (?, ?, ?)
            ON CONFLICT(observed_at) DO NOTHING
            """,
            (_utc_iso(observed_at), str(soc_percent), odometer_miles),
        )
        self._connection.commit()

    def record_home_interval(
        self,
        *,
        source_key: str,
        started_at: datetime,
        ended_at: datetime,
        energy_kwh: Decimal,
    ) -> None:
        if ended_at <= started_at:
            raise ValueError("interval end must be later than start")
        if energy_kwh < 0:
            raise ValueError("energy cannot be negative")
        self._connection.execute(
            """
            INSERT INTO charging_intervals(
                source_key, started_at, ended_at, energy_kwh, location_type, energy_source
            ) VALUES (?, ?, ?, ?, 'home', 'zappi_metered')
            ON CONFLICT(source_key) DO NOTHING
            """,
            (source_key, _utc_iso(started_at), _utc_iso(ended_at), str(energy_kwh)),
        )
        self._connection.commit()

    def record_agile_price(
        self, *, settlement_start: datetime, unit_price_p_per_kwh: Decimal
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO agile_prices(settlement_start, unit_price_p_per_kwh)
            VALUES (?, ?)
            ON CONFLICT(settlement_start) DO UPDATE SET
                unit_price_p_per_kwh = excluded.unit_price_p_per_kwh
            """,
            (_utc_iso(settlement_start), str(unit_price_p_per_kwh)),
        )
        self._connection.commit()

    def unassigned_home_interval_range(self) -> tuple[datetime, datetime] | None:
        row = self._connection.execute(
            """SELECT MIN(started_at) AS started_at, MAX(ended_at) AS ended_at
            FROM charging_intervals
            WHERE location_type = 'home' AND session_id IS NULL"""
        ).fetchone()
        if row is None or row["started_at"] is None or row["ended_at"] is None:
            return None
        return _parse_utc(row["started_at"]), _parse_utc(row["ended_at"])

    def record_zappi_observation(
        self, *, observed_at: datetime, device_id: str, connected: bool,
        charging: bool, power_kw: Decimal, session_energy_kwh: Decimal | None,
    ) -> None:
        self._connection.execute(
            """INSERT INTO zappi_observations(
                observed_at, device_id, connected, charging, power_kw, session_energy_kwh
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (_utc_iso(observed_at), device_id, int(connected), int(charging), str(power_kw),
             str(session_energy_kwh) if session_energy_kwh is not None else None),
        )
        self._connection.commit()

    def latest_zappi_observation(self) -> ZappiObservation | None:
        row = self._connection.execute(
            """SELECT observed_at, device_id, connected, charging, power_kw, session_energy_kwh
            FROM zappi_observations ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        return ZappiObservation(
            observed_at=_parse_utc(row["observed_at"]),
            device_id=row["device_id"],
            connected=bool(row["connected"]),
            charging=bool(row["charging"]),
            power_kw=_decimal(row["power_kw"]),
            session_energy_kwh=(
                _decimal(row["session_energy_kwh"])
                if row["session_energy_kwh"] is not None
                else None
            ),
        )

    def latest_vehicle_odometer(self) -> int | None:
        row = self._connection.execute(
            "SELECT odometer_miles FROM vehicle_observations ORDER BY observed_at DESC LIMIT 1"
        ).fetchone()
        return int(row["odometer_miles"]) if row is not None else None

    def request_home_session_closure(self, *, requested_at: datetime, odometer_miles: int) -> None:
        self._connection.execute(
            """INSERT INTO home_session_closure(id, requested_at, odometer_miles)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO NOTHING""",
            (_utc_iso(requested_at), odometer_miles),
        )
        self._connection.commit()

    def requested_home_session_closure(self) -> tuple[datetime, int] | None:
        row = self._connection.execute(
            "SELECT requested_at, odometer_miles FROM home_session_closure WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return _parse_utc(row["requested_at"]), int(row["odometer_miles"])

    def clear_home_session_closure(self) -> None:
        self._connection.execute("DELETE FROM home_session_closure WHERE id = 1")
        self._connection.commit()

    def latest_zappi_state(self) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT connected, charging, power_kw FROM zappi_observations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {"connected": bool(row["connected"]), "charging": bool(row["charging"]),
                "powerKw": row["power_kw"]}

    def reconcile_odometer_change(
        self, *, observed_at: datetime, odometer_miles: int
    ) -> list[ChargingSession]:
        """Close unassigned home intervals after a later odometer observation."""
        intervals = self._connection.execute(
            """
            SELECT * FROM charging_intervals
            WHERE location_type = 'home' AND session_id IS NULL
            ORDER BY started_at
            """
        ).fetchall()
        if not intervals:
            return []

        total_energy = sum((_decimal(row["energy_kwh"]) for row in intervals), Decimal())
        total_cost_pence = sum((self._interval_cost_pence(row) for row in intervals), Decimal())
        total_cost = (total_cost_pence / Decimal("100")).quantize(MONEY, ROUND_HALF_UP)
        weighted_price = (total_cost_pence / total_energy).quantize(PRICE, ROUND_HALF_UP)
        opened_at = intervals[0]["started_at"]
        closed_at = _utc_iso(observed_at)
        cursor = self._connection.execute(
            """
            INSERT INTO charging_sessions(
                opened_at, closed_at, odometer_miles, location_type, total_energy_kwh,
                total_cost_gbp, weighted_unit_price_p_per_kwh, energy_source, cost_source
            ) VALUES (?, ?, ?, 'home', ?, ?, ?, 'zappi_metered', 'agile_calculated')
            """,
            (
                opened_at,
                closed_at,
                odometer_miles,
                str(total_energy),
                str(total_cost),
                str(weighted_price),
            ),
        )
        session_id = cursor.lastrowid
        self._connection.executemany(
            "UPDATE charging_intervals SET session_id = ? WHERE id = ?",
            [(session_id, row["id"]) for row in intervals],
        )
        callback = create_charge_callback(
            energy_kwh=total_energy,
            total_cost_gbp=total_cost,
            timestamp=closed_at,
            odometer_miles=odometer_miles,
            notes="Home · Zappi · Agile",
        )
        handoff_url = create_handoff_url(
            callback,
            handoff_page_url=self._roadtrip_handoff_page_url,
        )
        message = (
            "Buzz charge complete\n\n"
            f"{total_energy} kWh\n£{total_cost} total\n"
            f"{weighted_price}p/kWh\n\n"
            f"Odometer: {odometer_miles:,} miles\nHome · Zappi · Agile\n\n"
            f'<a href="{handoff_url}">Add to Road Trip</a>'
        )
        self._connection.execute(
            """
            INSERT INTO notifications(session_id, message, roadtrip_callback)
            VALUES (?, ?, ?)
            """,
            (session_id, message, callback),
        )
        self._connection.commit()
        return [
            ChargingSession(
                id=session_id,
                energy_kwh=total_energy,
                total_cost_gbp=total_cost,
                weighted_unit_price_p_per_kwh=weighted_price,
                location_type="home",
                energy_source="zappi_metered",
                cost_source="agile_calculated",
            )
        ]

    def _interval_cost_pence(self, interval: sqlite3.Row) -> Decimal:
        started_at = _parse_utc(interval["started_at"])
        ended_at = _parse_utc(interval["ended_at"])
        duration_seconds = Decimal(str((ended_at - started_at).total_seconds()))
        cursor = started_at
        energy_kwh = _decimal(interval["energy_kwh"])
        cost = Decimal()
        while cursor < ended_at:
            settlement_start = cursor.replace(
                minute=(cursor.minute // 30) * 30, second=0, microsecond=0
            )
            settlement_end = settlement_start + timedelta(minutes=30)
            slice_end = min(ended_at, settlement_end)
            price = self._connection.execute(
                "SELECT unit_price_p_per_kwh FROM agile_prices WHERE settlement_start = ?",
                (_utc_iso(settlement_start),),
            ).fetchone()
            if price is None:
                raise ValueError(f"missing Agile price for {_utc_iso(settlement_start)}")
            slice_seconds = Decimal(str((slice_end - cursor).total_seconds()))
            energy_slice = energy_kwh * slice_seconds / duration_seconds
            cost += energy_slice * _decimal(price["unit_price_p_per_kwh"])
            cursor = slice_end
        return cost

    def pending_notifications(self) -> list[PendingNotification]:
        rows = self._connection.execute(
            """
            SELECT id, session_id, message, roadtrip_callback FROM notifications
            WHERE state = 'pending' ORDER BY id
            """
        ).fetchall()
        return [
            PendingNotification(
                id=row["id"],
                session_id=row["session_id"],
                message=row["message"],
                roadtrip_callback=row["roadtrip_callback"],
            )
            for row in rows
        ]

    def pending_notification_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM notifications WHERE state = 'pending'"
        ).fetchone()
        return int(row["count"])

    def mark_notification_delivered(self, notification_id: int, *, delivered_at: datetime) -> None:
        self._connection.execute(
            """
            UPDATE notifications
            SET state = 'delivered', delivered_at = ?
            WHERE id = ? AND state = 'pending'
            """,
            (_utc_iso(delivered_at), notification_id),
        )
        self._connection.commit()
