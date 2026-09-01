import os
import unittest
from unittest.mock import patch

from brontes.config import Settings


class SettingsTests(unittest.TestCase):
    def test_defaults_to_loopback_and_local_sqlite_ledger(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 8088)
        self.assertEqual(str(settings.database_path), "data/brontes.sqlite3")
        self.assertIsNone(settings.hermes_notification_url)


if __name__ == "__main__":
    unittest.main()
