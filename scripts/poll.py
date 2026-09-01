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
from brontes.notifications import HermesCliNotificationDispatcher
from brontes.octopus import OctopusAgileRates
from brontes.vw import CarConnectivityCliTelemetry
from brontes.workflow import HomeChargingWorkflow

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("vw", "zappi"), required=True)
    args = parser.parse_args()
    ledger = Ledger(Path(os.environ.get("BRONTES_DATABASE_PATH", ROOT / "data/brontes.sqlite3")))
    try:
        workflow = HomeChargingWorkflow(
            ledger,
            OctopusAgileRates(
                product_code=os.environ.get("BRONTES_OCTOPUS_PRODUCT_CODE", "AGILE-24-10-01"),
                tariff_code=os.environ.get("BRONTES_OCTOPUS_TARIFF_CODE", "E-1R-AGILE-24-10-01-B"),
            ),
        )
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
            workflow.process_vehicle(observation)
        else:
            observation = MyEnergiZappiTelemetry().read()
            workflow.process_zappi(observation, datetime.now(timezone.utc))
        HermesCliNotificationDispatcher(
            ledger,
            target=os.environ.get("BRONTES_TELEGRAM_TARGET", "telegram"),
        ).deliver_pending()
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
