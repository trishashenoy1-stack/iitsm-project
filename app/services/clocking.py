"""Time zone used to read dates the user types (filters). Storage is always UTC."""

from __future__ import annotations

from datetime import timedelta, timezone

DISPLAY_TZ = timezone(timedelta(hours=5, minutes=30), "IST")
