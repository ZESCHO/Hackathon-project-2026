"""
Display formatting.

Timestamps are stored in UTC, which is right: it is unambiguous and
does not shift twice a year. It is not what a reviewer should read.
This converts to the institution's own timezone at the point of
display, so a request filed at 18:10 reads as 18:10.
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DISPLAY_TIMEZONE = os.environ.get("DISPLAY_TIMEZONE", "Asia/Kolkata")


def _zone():
    try:
        return ZoneInfo(DISPLAY_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        print(f"Unknown DISPLAY_TIMEZONE {DISPLAY_TIMEZONE!r}; using UTC")
        return timezone.utc


ZONE = _zone()


def to_local(value):
    """
    Move a stored timestamp into the display timezone.

    Stored values are naive and always UTC, so a naive value is
    labelled UTC rather than guessed at.
    """

    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(ZONE)


def local_datetime(value, fmt="%d %b %Y, %I:%M %p"):
    """
    A timestamp as a reviewer should read it.
    """

    local = to_local(value)

    return local.strftime(fmt) if local else "—"


def local_date(value):
    return local_datetime(value, "%d %b %Y")


def local_time(value):
    return local_datetime(value, "%I:%M %p")


def time_ago(value):
    """
    How long ago something happened, for scanning a queue quickly.
    """

    local = to_local(value)

    if local is None:
        return ""

    seconds = (datetime.now(timezone.utc) - local).total_seconds()

    if seconds < 60:
        return "just now"

    minutes = seconds / 60

    if minutes < 60:
        return f"{int(minutes)} min ago"

    hours = minutes / 60

    if hours < 24:
        return f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"

    days = hours / 24

    if days < 30:
        return f"{int(days)} day{'s' if int(days) != 1 else ''} ago"

    return local.strftime("%d %b %Y")
