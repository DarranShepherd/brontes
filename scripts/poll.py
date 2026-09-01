#!/usr/bin/env python3
"""Run one read-only Brontes provider poll."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brontes.ledger import Ledger
from brontes.myenergi import MyEnergiZappiTelemetry
from brontes.vw import CarConnectivityCliTelemetry

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("vw", "zappi"), required=True)
    args = parser.parse_args()
    ledger = Ledger(Path(os.environ.get("BRONTES_DATABASE_PATH", ROOT / "data/brontes.sqlite3")))
    try:
        if args.provider == "vw":
            observation = CarConnectivityCliTelemetry(
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
            ledger.record_vehicle_observation(
                observed_at=observation.source_timestamp,
                soc_percent=observation.soc_percent,
                odometer_miles=observation.odometer_miles,
            )
        else:
            observation = MyEnergiZappiTelemetry().read()
            ledger.record_zappi_observation(
                observed_at=datetime.now(timezone.utc), device_id=observation.device_id,
                connected=observation.connected, charging=observation.charging,
                power_kw=observation.power_kw, session_energy_kwh=observation.session_energy_kwh,
            )
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
