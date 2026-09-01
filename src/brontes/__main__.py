"""Run the local Brontes API service."""

from __future__ import annotations

from wsgiref.simple_server import make_server

from brontes.api import create_application
from brontes.config import Settings
from brontes.ledger import Ledger
from brontes.notifications import HermesNotificationDispatcher


def main() -> None:
    settings = Settings.from_environment()
    ledger = Ledger(settings.database_path)
    dispatcher = (
        HermesNotificationDispatcher(ledger, settings.hermes_notification_url)
        if settings.hermes_notification_url
        else None
    )
    application = create_application(ledger, dispatcher)
    with make_server(settings.host, settings.port, application) as server:
        print(f"Brontes listening on http://{settings.host}:{settings.port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
