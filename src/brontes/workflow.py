"""Deterministic home-charging interval and session workflow."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from brontes.ledger import AwayChargeTracking, ChargingSession, Ledger, ZappiObservation
from brontes.myenergi import ZappiTelemetry
from brontes.vw import VehicleTelemetry


class AgileRates(Protocol):
    def prices_between(self, start: datetime, end: datetime) -> dict[datetime, Decimal]: ...


class HomeChargingWorkflow:
    """Aggregate Zappi intervals until an explicit home-session boundary."""

    _ZAPPI_CONFIRMATION_WINDOW = timedelta(minutes=5)
    _AWAY_SOC_RISE_THRESHOLD = Decimal("5")
    _AWAY_CHARGE_PLATEAU = timedelta(hours=1)

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
        completed = self._finalize_requested_session()
        away_charge = self._process_away_charge(telemetry)
        return completed + ([away_charge] if away_charge is not None else [])

    def _process_away_charge(self, telemetry: VehicleTelemetry) -> ChargingSession | None:
        """Track one credible stationary SoC rise until it reaches an end boundary."""
        tracking = self._ledger.away_charge_tracking()
        if tracking is None:
            self._ledger.save_away_charge_tracking(self._new_away_tracking(telemetry))
            return None
        if telemetry.source_timestamp <= tracking.last_observed_at:
            return None

        odometer_moved = telemetry.odometer_miles > tracking.last_odometer_miles
        stationary_soc_regressed = (
            telemetry.odometer_miles == tracking.last_odometer_miles
            and telemetry.soc_percent < tracking.last_soc_percent
        )
        if telemetry.odometer_miles < tracking.last_odometer_miles or stationary_soc_regressed:
            # VW can return an old SoC beside a current odometer. Keep it for audit,
            # but never allow it to become the baseline of a new charge.
            return None

        if odometer_moved:
            session = self._finalize_away_charge(tracking)
            self._ledger.save_away_charge_tracking(self._new_away_tracking(telemetry))
            return session

        if tracking.charge_opened_at is not None:
            if telemetry.soc_percent > tracking.last_soc_percent:
                self._ledger.save_away_charge_tracking(
                    self._with_last_observation(tracking, telemetry)
                )
                return None
            if telemetry.source_timestamp - tracking.last_observed_at >= self._AWAY_CHARGE_PLATEAU:
                session = self._finalize_away_charge(tracking)
                self._ledger.save_away_charge_tracking(self._new_away_tracking(telemetry))
                return session
            return None

        if telemetry.soc_percent - tracking.baseline_soc_percent < self._AWAY_SOC_RISE_THRESHOLD:
            self._ledger.save_away_charge_tracking(
                self._with_last_observation(tracking, telemetry)
            )
            return None
        if self._ledger.home_was_connected_between(
            tracking.baseline_at - self._ZAPPI_CONFIRMATION_WINDOW,
            telemetry.source_timestamp + self._ZAPPI_CONFIRMATION_WINDOW,
        ):
            self._ledger.save_away_charge_tracking(self._new_away_tracking(telemetry))
            return None

        self._ledger.save_away_charge_tracking(self._open_away_charge(tracking, telemetry))
        return None

    @staticmethod
    def _open_away_charge(
        tracking: AwayChargeTracking, telemetry: VehicleTelemetry
    ) -> AwayChargeTracking:
        return AwayChargeTracking(
            baseline_at=tracking.baseline_at,
            baseline_soc_percent=tracking.baseline_soc_percent,
            baseline_odometer_miles=tracking.baseline_odometer_miles,
            last_observed_at=telemetry.source_timestamp,
            last_soc_percent=telemetry.soc_percent,
            last_odometer_miles=telemetry.odometer_miles,
            positive_soc_rises=tracking.positive_soc_rises + 1,
            charge_opened_at=tracking.baseline_at,
            charge_start_soc_percent=tracking.baseline_soc_percent,
            charge_start_odometer_miles=tracking.baseline_odometer_miles,
        )

    @staticmethod
    def _new_away_tracking(telemetry: VehicleTelemetry) -> AwayChargeTracking:
        return AwayChargeTracking(
            baseline_at=telemetry.source_timestamp,
            baseline_soc_percent=telemetry.soc_percent,
            baseline_odometer_miles=telemetry.odometer_miles,
            last_observed_at=telemetry.source_timestamp,
            last_soc_percent=telemetry.soc_percent,
            last_odometer_miles=telemetry.odometer_miles,
            positive_soc_rises=0,
            charge_opened_at=None,
            charge_start_soc_percent=None,
            charge_start_odometer_miles=None,
        )

    @staticmethod
    def _with_last_observation(
        tracking: AwayChargeTracking, telemetry: VehicleTelemetry
    ) -> AwayChargeTracking:
        return AwayChargeTracking(
            baseline_at=tracking.baseline_at,
            baseline_soc_percent=tracking.baseline_soc_percent,
            baseline_odometer_miles=tracking.baseline_odometer_miles,
            last_observed_at=telemetry.source_timestamp,
            last_soc_percent=telemetry.soc_percent,
            last_odometer_miles=telemetry.odometer_miles,
            positive_soc_rises=(
                tracking.positive_soc_rises + 1
                if telemetry.soc_percent > tracking.last_soc_percent
                else tracking.positive_soc_rises
            ),
            charge_opened_at=tracking.charge_opened_at,
            charge_start_soc_percent=tracking.charge_start_soc_percent,
            charge_start_odometer_miles=tracking.charge_start_odometer_miles,
        )

    def _finalize_away_charge(self, tracking: AwayChargeTracking) -> ChargingSession | None:
        if tracking.charge_opened_at is None or tracking.positive_soc_rises < 2:
            return None
        assert tracking.charge_start_soc_percent is not None
        assert tracking.charge_start_odometer_miles is not None
        soc_rise = tracking.last_soc_percent - tracking.charge_start_soc_percent
        elapsed = tracking.last_observed_at - tracking.charge_opened_at
        charge_type = (
            "DC"
            if soc_rise >= Decimal("20") and elapsed <= timedelta(hours=1)
            else "AC"
        )
        unit_price = Decimal("75.00") if charge_type == "DC" else Decimal("26.11")
        energy = (soc_rise * Decimal("86") / Decimal("100")).quantize(Decimal("0.01"))
        return self._ledger.record_away_charge(
            source_key=(
                f"vw-away:{tracking.charge_opened_at.isoformat()}:"
                f"{tracking.last_observed_at.isoformat()}"
            ),
            opened_at=tracking.charge_opened_at,
            closed_at=tracking.last_observed_at,
            odometer_miles=tracking.last_odometer_miles,
            energy_kwh=energy,
            unit_price_p_per_kwh=unit_price,
            charge_type=charge_type,
            starting_soc_percent=tracking.charge_start_soc_percent,
            ending_soc_percent=tracking.last_soc_percent,
        )

    def reconcile_pending(self) -> list[ChargingSession]:
        """Retry a previously requested closure after a transient dependency failure."""
        return self._finalize_requested_session()

    def reconcile_away(self, *, start_at: datetime | None = None) -> list[ChargingSession]:
        """Backfill unrecorded away sessions from persisted telemetry history."""
        completed: list[ChargingSession] = []
        observations = self._ledger.vehicle_observations()
        for current_at, current_soc, current_odometer in observations:
            if start_at is not None and current_at < start_at:
                continue
            session = self._process_away_charge(
                VehicleTelemetry(
                    source_timestamp=current_at,
                    soc_percent=current_soc,
                    odometer_miles=current_odometer,
                    charging_state=None,
                    charge_type=None,
                    charge_power_kw=None,
                )
            )
            if session is not None and (start_at is None or current_at >= start_at):
                completed.append(session)
        return completed

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
