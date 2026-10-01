"""Safe, verified MyEnergi Zappi timed-boost control."""

from __future__ import annotations

import json
import netrc
import time
from datetime import datetime, timedelta
from typing import Callable
from urllib.request import HTTPDigestAuthHandler, HTTPPasswordMgrWithDefaultRealm, Request, build_opener
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
EMPTY = {"bsh": 0, "bsm": 0, "bdh": 0, "bdm": 0, "bdd": "00000000"}


class MyEnergiTimedBoosts:
    """Replace up to four ECO+ timed boosts and verify asynchronous application."""

    def __init__(
        self,
        *,
        request: Callable[[str], dict[str, object]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._request = request or self._request_live
        self._sleep = sleep

    def replace(
        self, half_hours: tuple[datetime, ...], *, expected_current: tuple[datetime, ...] = ()
    ) -> None:
        blocks = self._blocks(half_hours)
        old_blocks = self._blocks(expected_current)
        if len(blocks) > 4 or len(old_blocks) > 4:
            raise ValueError("selected prices require more than four Zappi timed-boost windows")
        zappi, serial, slots = self._current()
        if zappi.get("zmo") != 3:
            raise RuntimeError("Zappi is not in ECO+; refusing to replace timed boosts")
        expected_old = {
            number: EMPTY if number - 11 >= len(old_blocks) else self._encode(old_blocks[number - 11])
            for number in range(11, 15)
        }
        if any(not self._matches(slots[number], expected_old[number]) for number in range(11, 15)):
            raise RuntimeError("Zappi timed boosts changed outside Brontes; refusing to overwrite them")
        for number in range(11, 15):
            expected = EMPTY if number - 11 >= len(blocks) else self._encode(blocks[number - 11])
            start = f"{expected['bsh']:02d}{expected['bsm']:02d}"
            duration = f"{expected['bdh']}{expected['bdm']:02d}"
            self._request(f"cgi-boost-time-Z{serial}-{number}-{start}-{duration}-{expected['bdd']}")
            self._wait_for_slot(serial, number, expected)

    def _wait_for_slot(self, serial: str, number: int, expected: dict[str, object]) -> None:
        for _ in range(20):
            zappi, observed_serial, slots = self._current()
            if observed_serial != serial:
                raise RuntimeError("Zappi identity changed during schedule update")
            if zappi.get("cmt") == 253:
                raise RuntimeError("Zappi rejected timed boost update")
            if zappi.get("cmt") == 254 and self._matches(slots[number], expected):
                return
            self._sleep(15)
        raise TimeoutError("Zappi did not confirm timed boost update")

    def _current(self) -> tuple[dict[str, object], str, dict[int, dict[str, object]]]:
        status = self._request("cgi-jstatus-Z")
        zappis = status.get("zappi")
        if not isinstance(zappis, list) or len(zappis) != 1 or not isinstance(zappis[0], dict):
            raise RuntimeError("MyEnergi returned no unique Zappi")
        zappi = zappis[0]
        serial = str(zappi["sno"])
        response = self._request(f"cgi-boost-time-Z{serial}")
        raw_slots = response.get("boost_times")
        if not isinstance(raw_slots, list):
            raise RuntimeError("MyEnergi returned no timed boost slots")
        slots = {int(slot["slt"]): slot for slot in raw_slots if isinstance(slot, dict) and "slt" in slot}
        if set(slots) != {11, 12, 13, 14}:
            raise RuntimeError("MyEnergi did not return four timed boost slots")
        return zappi, serial, slots

    @staticmethod
    def _blocks(half_hours: tuple[datetime, ...]) -> tuple[tuple[datetime, ...], ...]:
        if not half_hours:
            return ()
        ordered = tuple(sorted(value.astimezone(UTC) for value in half_hours))
        if len(set(ordered)) != len(ordered):
            raise ValueError("timed boost slots must be unique")
        blocks: list[list[datetime]] = []
        for value in ordered:
            if not blocks or value != blocks[-1][-1] + timedelta(minutes=30):
                blocks.append([value])
            else:
                blocks[-1].append(value)
        return tuple(tuple(block) for block in blocks)

    @staticmethod
    def _encode(block: tuple[datetime, ...]) -> dict[str, object]:
        start = block[0]
        if any(value.date() != start.date() for value in block):
            raise ValueError("a timed boost cannot cross a local calendar day")
        minutes = len(block) * 30
        # MyEnergi's eight-digit mask is 0 + Monday-to-Sunday; Thursday is 00001000.
        mask = "0" + "0" * start.weekday() + "1" + "0" * (6 - start.weekday())
        return {"bsh": start.hour, "bsm": start.minute, "bdh": minutes // 60, "bdm": minutes % 60, "bdd": mask}

    @staticmethod
    def _matches(slot: dict[str, object], expected: dict[str, object]) -> bool:
        return all(slot.get(key) == value for key, value in expected.items())

    @staticmethod
    def _request_live(path: str) -> dict[str, object]:
        username, _, password = netrc.netrc().authenticators("myenergi_api") or (None, None, None)
        if not username or not password:
            raise RuntimeError("MyEnergi credentials missing from ~/.netrc machine myenergi_api")
        base = "https://director.myenergi.net/"
        passwords = HTTPPasswordMgrWithDefaultRealm()
        passwords.add_password(None, base, username, password)
        opener = build_opener(HTTPDigestAuthHandler(passwords))
        with opener.open(Request(base + path, headers={"Accept": "application/json"}), timeout=30) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("invalid MyEnergi response")
        return payload
