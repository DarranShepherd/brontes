"""Read-only MyEnergi Zappi telemetry."""

from __future__ import annotations

import json
import netrc
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, Request, build_opener


@dataclass(frozen=True)
class ZappiTelemetry:
    device_id: str
    connected: bool
    charging: bool
    power_kw: Decimal
    session_energy_kwh: Decimal | None


class MyEnergiZappiTelemetry:
    """Read Zappi status using Digest authentication from ~/.netrc."""

    def __init__(self, fetch: Callable[[], dict[str, object]] | None = None) -> None:
        self._fetch = fetch or self._fetch_live

    def read(self) -> ZappiTelemetry:
        payload = self._fetch()
        zappis = payload.get("zappi")
        if not isinstance(zappis, list) or not zappis or not isinstance(zappis[0], dict):
            raise RuntimeError("MyEnergi returned no Zappi telemetry")
        zappi = zappis[0]
        power_kw = Decimal(str(zappi.get("div", 0))) / Decimal("1000")
        plug_status = str(zappi.get("pst", ""))
        connected = plug_status.startswith(("B", "C"))
        charging = plug_status.startswith("C") or power_kw > 0
        energy = zappi.get("che")
        return ZappiTelemetry(
            device_id=str(zappi["sno"]),
            connected=connected,
            charging=charging,
            power_kw=power_kw,
            session_energy_kwh=Decimal(str(energy)) if energy is not None else None,
        )

    @staticmethod
    def _fetch_live() -> dict[str, object]:
        username, _, password = netrc.netrc().authenticators("myenergi_api") or (None, None, None)
        if username is None or password is None:
            raise RuntimeError("MyEnergi credentials missing from ~/.netrc machine myenergi_api")
        passwords = HTTPPasswordMgrWithDefaultRealm()
        url = "https://director.myenergi.net/"
        passwords.add_password(None, url, username, password)
        opener = build_opener(HTTPDigestAuthHandler(passwords))
        request = Request(f"{url}cgi-jstatus-Z", headers={"Accept": "application/json"})
        with opener.open(request, timeout=30) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("invalid MyEnergi response")
        return payload
