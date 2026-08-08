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


@dataclass(frozen=True)
class RankStatus:
    current: Rank
    next: Rank | None
    hours: float
    hours_into_current: float
    hours_to_next: float | None
    progress_fraction: float | None  # 0..1 within current tier; None if maxed out


def get_rank_status(hours: float) -> RankStatus:
    """
    Given accumulated hours, return the current rank, the next rank
    (or None if already at the top tier), and progress toward the next
    rank. Hours exactly equal to a threshold count as having reached
    that rank (>=, not >).
    """
    if hours < 0:
        raise ValueError("hours must be >= 0")

    current = RANK_TABLE[0]
    next_rank: Rank | None = None

    for i, rank in enumerate(RANK_TABLE):
        if hours >= rank.threshold_hours:
            current = rank
            next_rank = RANK_TABLE[i + 1] if i + 1 < len(RANK_TABLE) else None
        else:
            break

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
