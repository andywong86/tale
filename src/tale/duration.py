from __future__ import annotations

import re
from datetime import timedelta

_COMPONENT = re.compile(r"([0-9]+)([smhdw])\s*")
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(value: str) -> timedelta:
    """Parse positive, distinct duration components such as '1h 30m'."""
    value = value.strip()
    position = 0
    seconds = 0
    seen: set[str] = set()
    while position < len(value):
        match = _COMPONENT.match(value, position)
        if match is None:
            raise ValueError("expected a duration such as '30m', '6h', or '1h 30m'")
        amount = int(match[1])
        unit = match[2]
        if amount <= 0:
            raise ValueError("duration components must be positive")
        if unit in seen:
            raise ValueError(f"repeated duration unit: {unit}")
        seen.add(unit)
        seconds += amount * _SECONDS[unit]
        position = match.end()

    if not seen:
        raise ValueError("duration must not be empty")
    try:
        return timedelta(seconds=seconds)
    except OverflowError as exc:
        raise ValueError("duration is too large") from exc
