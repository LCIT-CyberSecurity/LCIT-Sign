from __future__ import annotations

from datetime import UTC, datetime


def ensure_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC.

    Postgres (`DateTime(timezone=True)`) always round-trips aware UTC
    datetimes. SQLite — used only in tests — has no timezone-aware storage
    and hands back naive ones instead. Every timestamp in this app is UTC
    by convention, so reattaching UTC here is correct, not a guess.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
