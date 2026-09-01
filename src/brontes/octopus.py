"""Read-only Octopus Agile settlement-price adapter."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UTC = timezone.utc


class OctopusAgileRates:
    """Read VAT-inclusive public Agile prices for a configured tariff."""

    def __init__(
        self,
        *,
        product_code: str,
        tariff_code: str,
        fetch: Callable[[str], dict[str, object]] | None = None,
    ) -> None:
        self._product_code = product_code
        self._tariff_code = tariff_code
        self._fetch = fetch or self._fetch_live

    def prices_between(self, start: datetime, end: datetime) -> dict[datetime, Decimal]:
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("price range must use increasing timezone-aware timestamps")
        params = urlencode(
            {
                "period_from": self._utc_iso(start),
                "period_to": self._utc_iso(end),
                "page_size": "100",
            }
        )
        url = (
            "https://api.octopus.energy/v1/products/"
            f"{self._product_code}/electricity-tariffs/{self._tariff_code}/standard-unit-rates/?{params}"
        )
        payload = self._fetch(url)
        rows = payload.get("results")
        if not isinstance(rows, list):
            raise RuntimeError("Octopus returned no settlement prices")
        prices: dict[datetime, Decimal] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            valid_from = row.get("valid_from")
            value = row.get("value_inc_vat")
            if not isinstance(valid_from, str) or value is None:
                continue
            timestamp = datetime.fromisoformat(valid_from.replace("Z", "+00:00")).astimezone(UTC)
            prices[timestamp] = Decimal(str(value))
        return prices

    @staticmethod
    def _utc_iso(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _fetch_live(url: str) -> dict[str, object]:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("invalid Octopus response")
        return payload
