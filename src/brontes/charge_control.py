"""Persisted, deterministic charge-request orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Protocol

from brontes.charge_planning import ChargePlan, ChargePlanner
from brontes.ledger import ChargeIntent, Ledger
from brontes.vw import VehicleTelemetry

UTC = timezone.utc


class AgileRates(Protocol):
    def prices_between(self, start: datetime, end: datetime) -> dict[datetime, Decimal]: ...


class TimedBoostWriter(Protocol):
    def replace(self, half_hours: tuple[datetime, ...], *, expected_current: tuple[datetime, ...] = ()) -> None: ...


class ChargeController:
    """Create and safely replan an explicit user-authorised home-charge intent."""

    def __init__(
        self, *, ledger: Ledger, rates: AgileRates, vehicle_reader: Callable[[], VehicleTelemetry], writer: TimedBoostWriter
    ) -> None:
        self._ledger = ledger
        self._rates = rates
        self._vehicle_reader = vehicle_reader
        self._writer = writer
        self._planner = ChargePlanner(battery_kwh=Decimal("86"), power_kw=Decimal("11"), efficiency=Decimal("0.90"))

    def request(self, *, now: datetime, target_soc_percent: Decimal = Decimal("80"), deadline: datetime | None = None) -> ChargePlan:
        return self._apply(now=now, target_soc_percent=target_soc_percent, deadline=deadline, previous=())

    def replan(self, *, now: datetime) -> ChargePlan | None:
        intent = self._ledger.charge_intent()
        if intent is None or intent.requested_deadline is None:
            return None
        if now >= intent.requested_deadline:
            self._writer.replace((), expected_current=intent.planned_slots)
            self._ledger.clear_charge_intent()
            return None
        # At 16:00 a second API fetch exposes tomorrow's rates. Do nothing unless the horizon grew.
        plan = self._make_plan(now=now, target_soc_percent=intent.target_soc_percent, deadline=intent.requested_deadline)
        if plan.effective_deadline <= intent.planned_until:
            return None
        self._writer.replace(plan.slots, expected_current=intent.planned_slots)
        self._ledger.save_charge_intent(ChargeIntent(plan.target_soc_percent, intent.requested_deadline, plan.effective_deadline, plan.slots))
        return plan

    def clear_if_due(self, *, now: datetime) -> bool:
        intent = self._ledger.charge_intent()
        if intent is None:
            return False
        due = intent.requested_deadline or intent.planned_until
        if now < due:
            return False
        self._writer.replace((), expected_current=intent.planned_slots)
        self._ledger.clear_charge_intent()
        return True

    def _apply(self, *, now: datetime, target_soc_percent: Decimal, deadline: datetime | None, previous: tuple[datetime, ...]) -> ChargePlan:
        plan = self._make_plan(now=now, target_soc_percent=target_soc_percent, deadline=deadline)
        self._writer.replace(plan.slots, expected_current=previous)
        self._ledger.save_charge_intent(ChargeIntent(plan.target_soc_percent, deadline, plan.effective_deadline, plan.slots))
        return plan

    def _make_plan(self, *, now: datetime, target_soc_percent: Decimal, deadline: datetime | None) -> ChargePlan:
        vehicle = self._vehicle_reader()
        self._ledger.record_vehicle_observation(observed_at=vehicle.source_timestamp, soc_percent=vehicle.soc_percent, odometer_miles=vehicle.odometer_miles)
        query_end = deadline if deadline is not None else now + timedelta(hours=36)
        prices = self._rates.prices_between(now, query_end)
        return self._planner.plan(
            current_soc_percent=vehicle.soc_percent, prices=prices, now=now,
            target_soc_percent=target_soc_percent, requested_deadline=deadline,
        )
