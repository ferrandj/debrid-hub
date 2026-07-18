from __future__ import annotations

from datetime import datetime, timezone


def unix_to_iso(value) -> str | None:
    """Convert a unix timestamp (int/str) to an ISO-8601 UTC string, or None."""
    if value in (None, "", 0, "0"):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None
