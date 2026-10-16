from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta

from .models import Task

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})"
)


def parse_bound(value: object, *, end: bool = False) -> tuple[datetime, bool]:
    """Normalize a date or offset timestamp to UTC and its exclusivity flag."""
    if isinstance(value, str):
        if _DATE.fullmatch(value):
            value = date.fromisoformat(value)
        elif _TIMESTAMP.fullmatch(value):
            value = datetime.fromisoformat(value.upper())
        else:
            raise ValueError(
                "expected YYYY-MM-DD or a timestamp with Z or a UTC offset"
            )
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("timestamps must include Z or a UTC offset")
        return value.astimezone(UTC), False
    if isinstance(value, date):
        if end:
            value += timedelta(days=1)
        # Convert each local midnight separately, respecting DST on that date.
        return datetime.combine(value, time.min).astimezone(UTC), end
    raise ValueError("expected a date or an offset-aware timestamp")


def within_window(task: Task, instant: datetime) -> bool:
    """Whether an execution or scheduled occurrence falls inside the window."""
    if task.not_before is not None and instant < task.not_before:
        return False
    if task.not_after is not None:
        if task.not_after_exclusive:
            return instant < task.not_after
        return instant <= task.not_after
    return True
