"""Read-only Volkswagen telemetry through the configured CarConnectivity CLI."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable


@dataclass(frozen=True)
class VehicleTelemetry:
    source_timestamp: datetime
    soc_percent: Decimal
    odometer_miles: int
    charging_state: str | None
    charge_type: str | None
    charge_power_kw: Decimal | None


class CarConnectivityCliTelemetry:
    """Use the isolated EU Data Act CLI without copying its credentials."""

    def __init__(
        self,
        *,
        executable: str,
        config_path: str,
        token_path: str,
        cache_path: str,
        run: Callable[[list[str]], str] | None = None,
    ) -> None:
        self._base_command = [
            executable,
            "--tokenfile",
            token_path,
            "--cachefile",
            cache_path,
            config_path,
        ]
        self._run = run or self._run_command

    def read(self) -> VehicleTelemetry:
        paths = self._run([*self._base_command, "list"]).splitlines()
        captured_path = next(
            (path for path in paths if path.endswith("/captured_at")), None
        )
        if captured_path is None:
            raise RuntimeError("CarConnectivity did not expose a vehicle captured_at path")
        vehicle_path = captured_path.rsplit("/", 1)[0]
        vehicle = json.loads(
            self._run([*self._base_command, "get", vehicle_path, "--format", "json"])
        )
        return VehicleTelemetry(
            source_timestamp=self._timestamp(vehicle, "captured_at"),
            soc_percent=self._decimal(vehicle, "drives", "primary", "level"),
            odometer_miles=int(self._decimal(vehicle, "odometer")),
            charging_state=self._optional_value(vehicle, "charging", "state"),
            charge_type=self._optional_value(vehicle, "charging", "type"),
            charge_power_kw=self._optional_decimal(vehicle, "charging", "power"),
        )

    @staticmethod
    def _run_command(command: list[str]) -> str:
        result = subprocess.run(command, check=True, text=True, capture_output=True, timeout=120)
        return result.stdout

    @staticmethod
    def _node(vehicle: dict[str, object], *path: str) -> dict[str, object]:
        current: object = vehicle
        for element in path:
            if not isinstance(current, dict):
                raise ValueError(f"missing CarConnectivity attribute: {'/'.join(path)}")
            current = current[element]
        if not isinstance(current, dict):
            raise ValueError(f"invalid CarConnectivity attribute: {'/'.join(path)}")
        return current

    @classmethod
    def _decimal(cls, vehicle: dict[str, object], *path: str) -> Decimal:
        value = cls._node(vehicle, *path).get("val")
        if value is None:
            raise ValueError(f"CarConnectivity attribute has no value: {'/'.join(path)}")
        return Decimal(str(value))

    @classmethod
    def _optional_decimal(cls, vehicle: dict[str, object], *path: str) -> Decimal | None:
        value = cls._node(vehicle, *path).get("val")
        return Decimal(str(value)) if value is not None else None

    @classmethod
    def _optional_value(cls, vehicle: dict[str, object], *path: str) -> str | None:
        value = cls._node(vehicle, *path).get("val")
        return str(value).lower() if value is not None else None

    @classmethod
    def _timestamp(cls, vehicle: dict[str, object], *path: str) -> datetime:
        value = cls._node(vehicle, *path).get("val")
        if not isinstance(value, str):
            raise ValueError(f"CarConnectivity timestamp has no value: {'/'.join(path)}")
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("CarConnectivity source timestamp must include a timezone")
        return timestamp
