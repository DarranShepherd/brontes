import unittest
from pathlib import Path


class RoadTripHandoffPageTests(unittest.TestCase):
    def test_page_only_redirects_to_validated_roadtrip_callbacks(self) -> None:
        page = Path("site/roadtrip/index.html").read_text()

        self.assertIn("location.hash", page)
        self.assertIn("desroadtrip://x-callback-url/", page)
        self.assertIn("window.location.assign(callback)", page)
        self.assertNotIn("innerHTML", page)


if __name__ == "__main__":
    unittest.main()
