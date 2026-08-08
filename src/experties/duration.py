"""
Parsing for human-friendly duration strings, used by `experties log`.

Accepts:
    "1h30m"  -> 1.5
    "1.5h"   -> 1.5
    "90m"    -> 1.5
    "2h"     -> 2.0
    "45m"    -> 0.75
    "1.5"    -> 1.5   (bare number, assumed hours)

Kept as a standalone pure function (no CLI, no I/O) so the parsing edge
cases can be unit tested directly instead of only indirectly through the
CLI.
"""

from __future__ import annotations

import re

_PATTERN = re.compile(
    r"^\s*(?:(?P<hours>\d+(?:\.\d+)?)h)?\s*(?:(?P<minutes>\d+(?:\.\d+)?)m)?\s*$",
    re.IGNORECASE,
)
_BARE_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")


def parse_duration(text: str) -> float:
    """
    Parse a duration string into a number of hours.

    Raises ValueError (with a message safe to show directly to the user)
    on anything that can't be confidently parsed, including durations
    that parse but come out to zero.
    """
    text = text.strip()
    if not text:
        raise ValueError("Duration cannot be empty.")

    if _BARE_NUMBER.fullmatch(text):
        value = float(text)
        if value <= 0:
            raise ValueError(f'Duration "{text}" must be greater than zero.')
        return value

    match = _PATTERN.match(text)
    if not match or (match.group("hours") is None and match.group("minutes") is None):
        raise ValueError(
            f'Could not parse duration "{text}". '
            f'Try formats like "1h30m", "1.5h", or "90m".'
        )

    hours = float(match.group("hours") or 0)
    minutes = float(match.group("minutes") or 0)
    total = hours + minutes / 60

    if total <= 0:
        raise ValueError(f'Duration "{text}" must be greater than zero.')

    return total
