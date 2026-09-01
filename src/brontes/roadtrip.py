"""Road Trip x-callback-url generation."""

from decimal import Decimal
from urllib.parse import urlencode


def create_charge_callback(
    *,
    energy_kwh: Decimal,
    total_cost_gbp: Decimal,
    timestamp: str,
    odometer_miles: int,
    notes: str,
) -> str:
    """Create a Road Trip fuel-entry callback for a charging session."""
    query = urlencode(
        {
            "amount": str(energy_kwh),
            "cost": str(total_cost_gbp),
            "date": timestamp,
            "odometer": str(odometer_miles),
            "notes": notes,
        }
    )
    return f"roadtrip://x-callback-url/addFuel?{query}"
