"""Deterministic Agile charge-window selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING

UTC = timezone.utc
HALF_HOUR = timedelta(minutes=30)


@dataclass(frozen=True)
class ChargePlan:
    target_soc_percent: Decimal
    effective_deadline: datetime
    grid_energy_kwh: Decimal
    slots: tuple[datetime, ...]


class ChargePlanner:
    """Choose the least-cost Zappi-compatible set of Agile half-hours."""

    def __init__(
        self,
        *,
        battery_kwh: Decimal,
        power_kw: Decimal,
        efficiency: Decimal,
        maximum_timer_windows: int = 4,
    ) -> None:
        if battery_kwh <= 0 or power_kw <= 0 or not Decimal("0") < efficiency <= Decimal("1"):
            raise ValueError("battery capacity, power and efficiency must be positive")
        self._battery_kwh = battery_kwh
        self._power_kw = power_kw
        self._efficiency = efficiency
        self._maximum_timer_windows = maximum_timer_windows

    def plan(
        self,
        *,
        current_soc_percent: Decimal,
        prices: dict[datetime, Decimal],
        now: datetime,
        target_soc_percent: Decimal = Decimal("80"),
        requested_deadline: datetime | None = None,
    ) -> ChargePlan:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if not Decimal("0") <= current_soc_percent <= Decimal("100"):
            raise ValueError("current SoC must be in the range 0–100")
        if not current_soc_percent < target_soc_percent <= Decimal("100"):
            raise ValueError("target SoC must be above current SoC and at most 100")
        normalized = sorted((start.astimezone(UTC), price) for start, price in prices.items())
        if not normalized:
            raise ValueError("no Agile prices are available")
        latest_end = normalized[-1][0] + HALF_HOUR
        effective_deadline = min(requested_deadline.astimezone(UTC), latest_end) if requested_deadline else latest_end
        candidates = [(start, price) for start, price in normalized if start >= now.astimezone(UTC) and start < effective_deadline]
        grid_energy = self._battery_kwh * (target_soc_percent - current_soc_percent) / Decimal("100") / self._efficiency
        per_slot = self._power_kw * Decimal("0.5")
        required_slots = int((grid_energy / per_slot).to_integral_value(rounding=ROUND_CEILING))
        selected = self._select_slots(candidates, required_slots)
        return ChargePlan(
            target_soc_percent=target_soc_percent,
            effective_deadline=effective_deadline,
            grid_energy_kwh=grid_energy,
            slots=selected,
        )

    def _select_slots(
        self, candidates: list[tuple[datetime, Decimal]], required_slots: int
    ) -> tuple[datetime, ...]:
        # State: selected half-hours, timer windows, previous slot selected -> cost and selection.
        states: dict[tuple[int, int, bool], tuple[Decimal, tuple[datetime, ...]]] = {(0, 0, False): (Decimal("0"), ())}
        for start, price in candidates:
            next_states: dict[tuple[int, int, bool], tuple[Decimal, tuple[datetime, ...]]] = {}
            for (count, windows, was_on), (cost, slots) in states.items():
                self._keep(next_states, (count, windows, False), (cost, slots))
                if count < required_slots:
                    next_windows = windows + (0 if was_on else 1)
                    if next_windows <= self._maximum_timer_windows:
                        self._keep(
                            next_states,
                            (count + 1, next_windows, True),
                            (cost + price, slots + (start,)),
                        )
            states = next_states
        feasible = [value for (count, _, _), value in states.items() if count == required_slots]
        if not feasible:
            raise ValueError("published Agile prices cannot meet the requested target by the available deadline")
        return min(feasible, key=lambda item: item[0])[1]

    @staticmethod
    def _keep(
        states: dict[tuple[int, int, bool], tuple[Decimal, tuple[datetime, ...]]],
        key: tuple[int, int, bool],
        value: tuple[Decimal, tuple[datetime, ...]],
    ) -> None:
        existing = states.get(key)
        if existing is None or value[0] < existing[0]:
            states[key] = value
