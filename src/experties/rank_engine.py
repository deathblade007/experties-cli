"""
Rank calculation engine for Experties-CLI.

Defines the shared rank tier table and provides pure functions for turning
accumulated hours into a rank, progress-within-tier, and hours-to-next-rank.

This module intentionally has zero I/O and zero dependencies on database.py,
timer.py, or cli.py — it's pure math over a list of thresholds. Keeping it
pure is what makes the boundary conditions (exact-threshold hours, the top
rank, multi-tier jumps in one session) cheap to unit test in isolation,
which matters most here since this is the easiest place to ship an
off-by-one bug.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rank:
    name: str
    threshold_hours: float


# Single shared table — used for every skill AND for the global rank
# (applied to hours summed across all skills). Must stay ordered ascending
# by threshold_hours; this is enforced at import time by _validate_table().
RANK_TABLE: list[Rank] = [
    Rank("Unranked", 0),
    Rank("Mud 1", 16), Rank("Mud 2", 19), Rank("Mud 3", 21),
    Rank("Wood 1", 24), Rank("Wood 2", 27), Rank("Wood 3", 31),
    Rank("Stone 1", 35), Rank("Stone 2", 39), Rank("Stone 3", 44),
    Rank("Copper 1", 50), Rank("Copper 2", 57), Rank("Copper 3", 65),
    Rank("Bronze 1", 73), Rank("Bronze 2", 83), Rank("Bronze 3", 94),
    Rank("Silver 1", 106), Rank("Silver 2", 120), Rank("Silver 3", 138),
    Rank("Gold 1", 160), Rank("Gold 2", 190), Rank("Gold 3", 230),
    Rank("Platinum 1", 290), Rank("Platinum 2", 380), Rank("Platinum 3", 490),
    Rank("Diamond 1", 630), Rank("Diamond 2", 800), Rank("Diamond 3", 1000),
    Rank("Champion 1", 1270), Rank("Champion 2", 1590), Rank("Champion 3", 2000),
    Rank("Grand Champion 1", 2550), Rank("Grand Champion 2", 3170), Rank("Grand Champion 3", 3810),
    Rank("Super Sonic Legend", 4450),
    Rank("B", 5038), Rank("B+", 5703), Rank("A", 6456),
    Rank("X", 7309), Rank("S", 8274),
]


def _validate_table(table: list[Rank]) -> None:
    for prev, curr in zip(table, table[1:]):
        if curr.threshold_hours <= prev.threshold_hours:
            raise ValueError(
                f"Rank table is not strictly increasing: "
                f"{prev.name} ({prev.threshold_hours}h) >= "
                f"{curr.name} ({curr.threshold_hours}h)"
            )


_validate_table(RANK_TABLE)

# Divisions: from Bronze 1 up through X (every rank that has a "next"
# rank above the starter tiers), each rank's hour span to the *next*
# rank is split into 4 even quarters — Division 1 at the rank's own
# threshold, Division 2 at +25% of the span, Division 3 at +50%,
# Division 4 at +75%. Reaching the next rank's own threshold (100% of
# the span) means the whole rank is complete, not just division 4.
#
# Deliberately computed from RANK_TABLE rather than hardcoded: the
# spreadsheet's division hours are exactly this formula applied to the
# existing thresholds, so deriving them keeps a single source of truth
# and can't drift out of sync with RANK_TABLE.
DIVISION_COUNT = 4
_DIVISIONS_START_NAME = "Bronze 1"
_DIVISIONS_START_INDEX = next(i for i, r in enumerate(RANK_TABLE) if r.name == _DIVISIONS_START_NAME)


def _has_divisions(rank_index: int) -> bool:
    """True for every rank from Bronze 1 up to (but not including) the
    very last rank — the last rank (S) has no 'next' tier to divide
    against, so it can't have divisions, matching the sheet's blank
    Division II/III/IV cells for S."""
    return _DIVISIONS_START_INDEX <= rank_index < len(RANK_TABLE) - 1


def division_thresholds(rank_index: int) -> list[float] | None:
    """
    Return the DIVISION_COUNT division-start hours for the rank at
    rank_index, evenly spaced between its own threshold and the next
    rank's. Returns None for ranks that don't have divisions — anything
    below Bronze 1, and the single top rank.
    """
    if not _has_divisions(rank_index):
        return None
    current = RANK_TABLE[rank_index]
    nxt = RANK_TABLE[rank_index + 1]
    span = nxt.threshold_hours - current.threshold_hours
    return [current.threshold_hours + span * i / DIVISION_COUNT for i in range(DIVISION_COUNT)]


def _division_display_name(rank_index: int, rank_name: str, hours: float) -> str:
    """The name to show for hours currently in rank_index — the plain
    rank name if it has no divisions, otherwise the name plus whichever
    division threshold has most recently been crossed."""
    thresholds = division_thresholds(rank_index)
    if thresholds is None:
        return rank_name

    division_number = 1
    for i, threshold in enumerate(thresholds):
        if hours >= threshold:
            division_number = i + 1

    return f"{rank_name} Division {division_number}"


@dataclass(frozen=True)
class RankStatus:
    current: Rank
    next: Rank | None
    hours: float
    hours_into_current: float
    hours_to_next: float | None
    progress_fraction: float | None  # 0..1 within current tier; None if maxed out
    display_name: str  # current.name, or "<rank> Division N" where divisions apply


def get_rank_status(hours: float) -> RankStatus:
    """
    Given accumulated hours, return the current rank, the next rank
    (or None if already at the top tier), and progress toward the next
    rank. Hours exactly equal to a threshold count as having reached
    that rank (>=, not >).

    hours_to_next and progress_fraction are always measured against the
    full rank-to-rank span, never against a division boundary — a
    division only changes display_name, not what "next rank" means or
    how much is left to reach it.
    """
    if hours < 0:
        raise ValueError("hours must be >= 0")

    current_index = 0
    next_rank: Rank | None = None

    for i, rank in enumerate(RANK_TABLE):
        if hours >= rank.threshold_hours:
            current_index = i
            next_rank = RANK_TABLE[i + 1] if i + 1 < len(RANK_TABLE) else None
        else:
            break

    current = RANK_TABLE[current_index]
    hours_into_current = hours - current.threshold_hours

    if next_rank is None:
        hours_to_next = None
        progress_fraction = None
    else:
        tier_span = next_rank.threshold_hours - current.threshold_hours
        hours_to_next = next_rank.threshold_hours - hours
        progress_fraction = hours_into_current / tier_span if tier_span > 0 else 1.0

    return RankStatus(
        current=current,
        next=next_rank,
        hours=hours,
        hours_into_current=hours_into_current,
        hours_to_next=hours_to_next,
        progress_fraction=progress_fraction,
        display_name=_division_display_name(current_index, current.name, hours),
    )


def crossed_rank_up(hours_before: float, hours_after: float) -> list[Rank]:
    """
    Return every rank tier crossed when going from hours_before to
    hours_after, in order. A single long session can cross more than one
    tier at once — the caller (after committing a session) uses this list
    to decide how many level-up notifications to fire.
    """
    if hours_after <= hours_before:
        return []
    return [
        rank for rank in RANK_TABLE
        if hours_before < rank.threshold_hours <= hours_after
    ]