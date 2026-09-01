"""Deterministic home-charging interval and session workflow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from brontes.ledger import ChargingSession, Ledger, ZappiObservation
from brontes.myenergi import ZappiTelemetry
from brontes.vw import VehicleTelemetry


class AgileRates(Protocol):
    def prices_between(self, start: datetime, end: datetime) -> dict[datetime, Decimal]: ...


class HomeChargingWorkflow:
    """Aggregate Zappi intervals until an explicit home-session boundary."""

    def __init__(self, ledger: Ledger, rates: AgileRates) -> None:
        self._ledger = ledger
        self._rates = rates

    def process_zappi(self, telemetry: ZappiTelemetry, observed_at: datetime) -> list[ChargingSession]:
        previous = self._ledger.latest_zappi_observation()
        self._ledger.record_zappi_observation(
            observed_at=observed_at,
            device_id=telemetry.device_id,
            connected=telemetry.connected,
            charging=telemetry.charging,
            power_kw=telemetry.power_kw,
            session_energy_kwh=telemetry.session_energy_kwh,
        )
        if previous is not None:
            self._record_energy_delta(previous, telemetry, observed_at)
            if previous.connected and not telemetry.connected:
                odometer = self._ledger.latest_vehicle_odometer()
                if odometer is not None:
                    self._ledger.request_home_session_closure(
                        requested_at=observed_at,
                        odometer_miles=odometer,
                    )
        return self._finalize_requested_session()

    def process_vehicle(self, telemetry: VehicleTelemetry) -> list[ChargingSession]:
        previous_odometer = self._ledger.latest_vehicle_odometer()
        self._ledger.record_vehicle_observation(
            observed_at=telemetry.source_timestamp,
            soc_percent=telemetry.soc_percent,
            odometer_miles=telemetry.odometer_miles,
        )
        if previous_odometer is not None and telemetry.odometer_miles > previous_odometer:
            self._ledger.request_home_session_closure(
                requested_at=telemetry.source_timestamp,
                odometer_miles=telemetry.odometer_miles,
            )
        return self._finalize_requested_session()

    def _record_energy_delta(
        self,
        previous: ZappiObservation,
        current: ZappiTelemetry,
        observed_at: datetime,
    ) -> None:
        if previous.device_id != current.device_id:
            return
        if previous.session_energy_kwh is None or current.session_energy_kwh is None:
            return
        energy_kwh = current.session_energy_kwh - previous.session_energy_kwh
        if energy_kwh <= 0:
            return
        self._record_prices(previous.observed_at, observed_at)
        self._ledger.record_home_interval(
            source_key=f"zappi:{current.device_id}:{observed_at.isoformat()}",
            started_at=previous.observed_at,
            ended_at=observed_at,
            energy_kwh=energy_kwh,
        )

    def _record_prices(self, start: datetime, end: datetime) -> None:
        for settlement_start, price in self._rates.prices_between(start, end).items():
            self._ledger.record_agile_price(
                settlement_start=settlement_start,
                unit_price_p_per_kwh=price,
            )

    def _finalize_requested_session(self) -> list[ChargingSession]:
        closure = self._ledger.requested_home_session_closure()
        if closure is None:
            return []
        requested_at, odometer_miles = closure
        interval_range = self._ledger.unassigned_home_interval_range()
        if interval_range is not None:
            try:
                self._record_prices(*interval_range)
            except (OSError, RuntimeError, TimeoutError):
                return []
        try:
            sessions = self._ledger.reconcile_odometer_change(
                observed_at=requested_at,
                odometer_miles=odometer_miles,
            )
        except ValueError:
            return []
        self._ledger.clear_home_session_closure()
        return sessions
