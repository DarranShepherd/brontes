#!/usr/bin/env python3
"""Deprecated compatibility shim; use `brontes poll <provider>` instead."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brontes.cli import main


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if len(arguments) == 2 and arguments[0] == "--provider":
        arguments = [arguments[1]]
    raise SystemExit(main(["poll", *arguments]))
