"""Periodic read-only provider polling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from brontes.ledger import Ledger
from brontes.myenergi import ZappiTelemetry
from brontes.vw import VehicleTelemetry


class VehicleReader(Protocol):
    def read(self) -> VehicleTelemetry: ...


class ZappiReader(Protocol):
    def read(self) -> ZappiTelemetry: ...


@dataclass(frozen=True)
class PollResult:
    vw_recorded: bool
    zappi_recorded: bool


class Poller:
    def __init__(self, ledger: Ledger, vw: VehicleReader, zappi: ZappiReader) -> None:
        self._ledger = ledger
        self._vw = vw
        self._zappi = zappi

    def poll_once(self) -> PollResult:
        vehicle = self._vw.read()
        self._ledger.record_vehicle_observation(
            observed_at=vehicle.source_timestamp,
            soc_percent=vehicle.soc_percent,
            odometer_miles=vehicle.odometer_miles,
        )
        zappi = self._zappi.read()
        self._ledger.record_zappi_observation(
            observed_at=datetime.now(timezone.utc),
            device_id=zappi.device_id,
            connected=zappi.connected,
            charging=zappi.charging,
            power_kw=zappi.power_kw,
            session_energy_kwh=zappi.session_energy_kwh,
        )
        return PollResult(vw_recorded=True, zappi_recorded=True)
