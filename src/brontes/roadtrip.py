"""Road Trip x-callback-url generation."""

from base64 import urlsafe_b64encode
from decimal import Decimal
from urllib.parse import quote, urlencode, urlsplit

DEFAULT_HANDOFF_PAGE_URL = "https://darranshepherd.github.io/brontes/roadtrip/"
DEFAULT_VEHICLE_NAME = "Volkswagen ID.Buzz GTX"


def create_charge_callback(
    *,
    energy_kwh: Decimal,
    total_cost_gbp: Decimal,
    timestamp: str,
    odometer_miles: int,
    notes: str,
    vehicle_name: str = DEFAULT_VEHICLE_NAME,
) -> str:
    """Create a Road Trip fuel-entry callback for a charging session."""
    query = urlencode(
        {
            "vehicle": vehicle_name,
            "fillAmount": str(energy_kwh),
            "cost": str(total_cost_gbp),
            "date": timestamp,
            "odometer": str(odometer_miles),
            "notes": notes,
        },
        quote_via=quote,
    )
    return f"desroadtrip://x-callback-url/addFuel?{query}"


def create_handoff_url(callback: str, *, handoff_page_url: str) -> str:
    """Wrap a Road Trip callback in an HTTPS URL with a client-side fragment.

    The fragment never forms part of the HTTPS request to GitHub Pages, so the
    callback's charge data is not published or retained by the static host.
    """
    parsed = urlsplit(handoff_page_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("handoff page URL must be an HTTPS URL without query or fragment")
    if not callback.startswith("desroadtrip://x-callback-url/"):
        raise ValueError("only Road Trip x-callback URLs can be handed off")
    encoded = urlsafe_b64encode(callback.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{handoff_page_url.rstrip('/')}/#{encoded}"
