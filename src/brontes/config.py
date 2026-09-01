"""Credential-free runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    host: str
    port: int
    hermes_notification_url: str | None

    @classmethod
    def from_environment(cls) -> "Settings":
        notification_url = os.environ.get("BRONTES_HERMES_NOTIFICATION_URL")
        return cls(
            database_path=Path(os.environ.get("BRONTES_DATABASE_PATH", "data/brontes.sqlite3")),
            host=os.environ.get("BRONTES_HOST", "127.0.0.1"),
            port=int(os.environ.get("BRONTES_PORT", "8088")),
            hermes_notification_url=notification_url or None,
        )
