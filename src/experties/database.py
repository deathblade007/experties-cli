"""
Local SQLite storage for Experties-CLI.

Every skill and every logged session lives in a single SQLite file at
~/.experties/data.db by default. There's no server and no network calls —
this module is the entire persistence layer.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".experties" / "data.db"


def resolve_db_path() -> Path:
    """
    The database path used when none is passed explicitly — checks
    EXPERTIES_DB_PATH first, falling back to the real default. Exposed
    separately (not just inlined in __init__) so cli.py can put sibling
    state files, like the "current group" set by `experties cd`, next
    to wherever the database actually lives — which gives that state
    the same test isolation as the database itself, for free.
    """
    override = os.environ.get("EXPERTIES_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);

-- started_at/ended_at are only set when a session came from a real timer
-- (either `start` or `timer start`/`timer stop`) — they're the actual
-- wall-clock interval the work happened in, used to dedupe overlapping
-- time when rolling hours up (see _merge_interval_hours). Manually
-- logged time (`experties log --time`) has no known interval, so both
-- stay NULL and that session just adds on top, same as it always has.
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id   INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    hours      REAL NOT NULL CHECK (hours > 0),
    note       TEXT,
    started_at TEXT,
    ended_at   TEXT,
    logged_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_skill_id ON sessions(skill_id);

-- Every skill can hold other skills as members — there's no separate
-- "group" type. A skill with no members is just a skill; the moment
-- something is nested under it, it's also a group. Nesting can go
-- arbitrarily deep (a group can itself be a member of another group);
-- each skill has at most one parent, so hours from any one session
-- never get rolled up into two different totals at once.
CREATE TABLE IF NOT EXISTS skill_groups (
    child_skill_id  INTEGER PRIMARY KEY REFERENCES skills(id) ON DELETE CASCADE,
    parent_skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE
);

-- A skill can have at most one timer running at once (skill_id is the
-- primary key). Rows here are transient — `timer stop` deletes the row
-- and turns it into a real session; `timer cancel` just deletes it.
-- started_at never changes once set. accumulated_seconds banks the
-- active time from every running stretch completed so far; resumed_at
-- marks when the *current* stretch began, and is NULL while paused —
-- current elapsed = accumulated_seconds + (now - resumed_at) if running.
CREATE TABLE IF NOT EXISTS active_timers (
    skill_id            INTEGER PRIMARY KEY REFERENCES skills(id) ON DELETE CASCADE,
    started_at          TEXT NOT NULL,
    accumulated_seconds REAL NOT NULL DEFAULT 0,
    resumed_at          TEXT
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _merge_interval_hours(sessions: list["Session"]) -> float:
    """
    Total hours across these sessions, counting overlapping wall-clock
    time only once. Sessions that came from a real timer carry a known
    [started_at, ended_at) interval; those get sorted and merged, so two
    things tracked at the same time only count that overlap once.
    Manually logged time (`experties log --time`) has no known interval —
    there's nothing to compare it against — so it just adds on top,
    exactly as it always has.
    """
    dated: list[tuple[datetime, datetime]] = []
    additive_hours = 0.0
    for s in sessions:
        if s.started_at and s.ended_at:
            dated.append((_parse_iso(s.started_at), _parse_iso(s.ended_at)))
        else:
            additive_hours += s.hours

    if not dated:
        return additive_hours

    dated.sort(key=lambda interval: interval[0])
    merged_seconds = 0.0
    current_start, current_end = dated[0]
    for start, end in dated[1:]:
        if start <= current_end:
            if end > current_end:
                current_end = end
        else:
            merged_seconds += (current_end - current_start).total_seconds()
            current_start, current_end = start, end
    merged_seconds += (current_end - current_start).total_seconds()

    return additive_hours + merged_seconds / 3600


@dataclass(frozen=True)
class Skill:
    id: int
    name: str
    created_at: str


@dataclass(frozen=True)
class Session:
    id: int
    skill_id: int
    hours: float
    note: str | None
    started_at: str | None
    ended_at: str | None
    logged_at: str


@dataclass(frozen=True)
class ActiveTimerInfo:
    skill: Skill
    started_at: str
    elapsed_seconds: float
    is_paused: bool


class SkillAlreadyExistsError(Exception):
    pass


class SkillNotFoundError(Exception):
    pass


class Database:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = resolve_db_path()

        if str(db_path) == ":memory:":
            self.db_path: str | Path = ":memory:"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._migrate_add_ended_at_column()
        self._migrate_add_timer_pause_columns()
        self._conn.commit()

    def _migrate_add_ended_at_column(self) -> None:
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(sessions)")}
        if "ended_at" not in columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN ended_at TEXT")

    def _migrate_add_timer_pause_columns(self) -> None:
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(active_timers)")}
        if "accumulated_seconds" not in columns:
            self._conn.execute("ALTER TABLE active_timers ADD COLUMN accumulated_seconds REAL NOT NULL DEFAULT 0")
        if "resumed_at" not in columns:
            self._conn.execute("ALTER TABLE active_timers ADD COLUMN resumed_at TEXT")
            # Any timer that already existed under the old, pause-less
            # schema was — by definition — running, so treat its current
            # stretch as having begun at its original start moment.
            self._conn.execute("UPDATE active_timers SET resumed_at = started_at WHERE resumed_at IS NULL")

    # -- skills --------------------------------------------------------

    def add_skill(self, name: str) -> Skill:
        name = name.strip()
        if not name:
            raise ValueError("skill name cannot be empty")

        if self.get_skill(name) is not None:
            raise SkillAlreadyExistsError(f'Skill "{name}" already exists')

        created_at = _now_iso()
        cur = self._conn.execute(
            "INSERT INTO skills (name, created_at) VALUES (?, ?)",
            (name, created_at),
        )
        self._conn.commit()
        return Skill(id=cur.lastrowid, name=name, created_at=created_at)

    def create_group(self, name: str) -> Skill:
        """
        Create an empty skill with no sessions logged yet — a convenience
        entry point for "I want to nest things under this name" before
        anything is nested under it. Functionally identical to add_skill();
        kept as a separate method because `experties group create` reads
        better than `experties skill add` for that intent, and because
        every skill can hold members now, there's no flag to set here —
        add_to_group() is what actually makes a skill "a group" in
        practice, by giving it its first member.
        """
        return self.add_skill(name)

    def get_skill(self, name: str) -> Skill | None:
        row = self._conn.execute(
            "SELECT * FROM skills WHERE name = ? COLLATE NOCASE", (name.strip(),)
        ).fetchone()
        return _row_to_skill(row) if row else None

    def get_skill_by_id(self, skill_id: int) -> Skill | None:
        row = self._conn.execute(
            "SELECT * FROM skills WHERE id = ?", (skill_id,)
        ).fetchone()
        return _row_to_skill(row) if row else None

    def get_or_create_skill(self, name: str) -> Skill:
        return self.get_skill(name) or self.add_skill(name)

    def list_groups(self) -> list[Skill]:
        """
        Every skill that currently has at least one member, at any depth —
        i.e. every skill that's "a group" in practice right now. This is
        computed, not stored: a skill becomes a group the moment something
        is nested under it, and stops being one the moment its last member
        leaves. DISTINCT because a skill can be someone's parent more than
        once conceptually shouldn't happen, but is cheap insurance.
        """
        rows = self._conn.execute(
            """SELECT DISTINCT skills.* FROM skills
               JOIN skill_groups ON skill_groups.parent_skill_id = skills.id
               ORDER BY skills.name COLLATE NOCASE"""
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def get_top_level_skills(self) -> list[Skill]:
        """
        Every skill with no parent — the roots of the forest. A root can
        still have members of its own (it just shows up here regardless),
        so this is the complete top-level set on its own; nothing else
        needs to be unioned in.
        """
        rows = self._conn.execute(
            """SELECT skills.* FROM skills
               WHERE skills.id NOT IN (SELECT child_skill_id FROM skill_groups)
               ORDER BY skills.name COLLATE NOCASE"""
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def get_top_level_skills_with_hours(self) -> list[tuple[Skill, float]]:
        return [(skill, self.get_total_hours(skill.name)) for skill in self.get_top_level_skills()]

    def _is_descendant(self, ancestor_id: int, candidate_id: int) -> bool:
        """True if candidate_id is somewhere in ancestor_id's subtree, at any depth."""
        row = self._conn.execute(
            """
            WITH RECURSIVE descendants(id) AS (
                SELECT child_skill_id FROM skill_groups WHERE parent_skill_id = ?
                UNION ALL
                SELECT skill_groups.child_skill_id
                FROM skill_groups
                JOIN descendants ON skill_groups.parent_skill_id = descendants.id
            )
            SELECT 1 FROM descendants WHERE id = ? LIMIT 1
            """,
            (ancestor_id, candidate_id),
        ).fetchone()
        return row is not None

    def add_to_group(self, group_name: str, skill_name: str) -> Skill:
        group = self.get_or_create_skill(group_name)
        skill = self.get_or_create_skill(skill_name)

        if skill.id == group.id:
            raise ValueError("a skill can't contain itself")

        current_parent = self.get_group_of(skill.name)
        if current_parent is not None and current_parent.id != group.id:
            raise ValueError(f'"{skill.name}" already belongs to the group "{current_parent.name}".')

        if self._is_descendant(ancestor_id=skill.id, candidate_id=group.id):
            raise ValueError(
                f'Can\'t nest "{skill.name}" under "{group.name}" — "{group.name}" is already nested '
                f'under "{skill.name}", so this would create a loop.'
            )

        self._conn.execute(
            "INSERT OR REPLACE INTO skill_groups (child_skill_id, parent_skill_id) VALUES (?, ?)",
            (skill.id, group.id),
        )
        self._conn.commit()
        return skill

    def remove_from_group(self, skill_name: str) -> bool:
        skill = self.get_skill(skill_name)
        if skill is None:
            raise SkillNotFoundError(f'Skill "{skill_name}" does not exist')
        cur = self._conn.execute("DELETE FROM skill_groups WHERE child_skill_id = ?", (skill.id,))
        self._conn.commit()
        return cur.rowcount > 0

    def get_group_members(self, group_name: str) -> list[Skill]:
        group = self.get_skill(group_name)
        if group is None:
            raise SkillNotFoundError(f'Skill "{group_name}" does not exist')
        rows = self._conn.execute(
            """SELECT skills.* FROM skills
               JOIN skill_groups ON skill_groups.child_skill_id = skills.id
               WHERE skill_groups.parent_skill_id = ?
               ORDER BY skills.name COLLATE NOCASE""",
            (group.id,),
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def get_descendants(self, skill_name: str) -> list[Skill]:
        """Every skill nested under this one, at any depth — not just direct members."""
        skill = self.get_skill(skill_name)
        if skill is None:
            raise SkillNotFoundError(f'Skill "{skill_name}" does not exist')
        rows = self._conn.execute(
            """
            WITH RECURSIVE descendants(id) AS (
                SELECT child_skill_id FROM skill_groups WHERE parent_skill_id = ?
                UNION ALL
                SELECT skill_groups.child_skill_id
                FROM skill_groups
                JOIN descendants ON skill_groups.parent_skill_id = descendants.id
            )
            SELECT skills.* FROM skills WHERE skills.id IN (SELECT id FROM descendants)
            ORDER BY skills.name COLLATE NOCASE
            """,
            (skill.id,),
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def get_group_of(self, skill_name: str) -> Skill | None:
        skill = self.get_skill(skill_name)
        if skill is None:
            return None
        row = self._conn.execute(
            """SELECT skills.* FROM skills
               JOIN skill_groups ON skill_groups.parent_skill_id = skills.id
               WHERE skill_groups.child_skill_id = ?""",
            (skill.id,),
        ).fetchone()
        return _row_to_skill(row) if row else None

    def rename_skill(self, old_name: str, new_name: str) -> Skill:
        old_name = old_name.strip()
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("new skill name cannot be empty")

        skill = self.get_skill(old_name)
        if skill is None:
            raise SkillNotFoundError(f'Skill "{old_name}" does not exist')

        existing = self.get_skill(new_name)
        if existing is not None and existing.id != skill.id:
            raise SkillAlreadyExistsError(f'Skill "{new_name}" already exists')

        self._conn.execute("UPDATE skills SET name = ? WHERE id = ?", (new_name, skill.id))
        self._conn.commit()
        return Skill(id=skill.id, name=new_name, created_at=skill.created_at)

    def delete_skill(self, name: str) -> bool:
        skill = self.get_skill(name)
        if skill is None:
            return False
        self._conn.execute("DELETE FROM skills WHERE id = ?", (skill.id,))
        self._conn.commit()
        return True

    # -- sessions --------------------------------------------------------

    def log_session(
        self,
        skill_name: str,
        hours: float,
        note: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        create_skill_if_missing: bool = True,
    ) -> Session:
        if hours <= 0:
            raise ValueError("hours must be > 0")

        if create_skill_if_missing:
            skill = self.get_or_create_skill(skill_name)
        else:
            skill = self.get_skill(skill_name)
            if skill is None:
                raise SkillNotFoundError(f'Skill "{skill_name}" does not exist')

        note = note.strip() or None if note else None
        logged_at = _now_iso()
        cur = self._conn.execute(
            """INSERT INTO sessions (skill_id, hours, note, started_at, ended_at, logged_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (skill.id, hours, note, started_at, ended_at, logged_at),
        )
        self._conn.commit()
        return Session(
            id=cur.lastrowid,
            skill_id=skill.id,
            hours=hours,
            note=note,
            started_at=started_at,
            ended_at=ended_at,
            logged_at=logged_at,
        )

    def get_sessions(self, skill_name: str, limit: int | None = None) -> list[Session]:
        skill = self.get_skill(skill_name)
        if skill is None:
            raise SkillNotFoundError(f'Skill "{skill_name}" does not exist')
        return self._fetch_subtree_sessions(skill.id, newest_first=True, limit=limit)

    def _fetch_subtree_sessions(
        self, skill_id: int, newest_first: bool = False, limit: int | None = None
    ) -> list[Session]:
        query = """
            WITH RECURSIVE subtree(id) AS (
                SELECT ?
                UNION ALL
                SELECT skill_groups.child_skill_id
                FROM skill_groups
                JOIN subtree ON skill_groups.parent_skill_id = subtree.id
            )
            SELECT sessions.* FROM sessions
            WHERE sessions.skill_id IN (SELECT id FROM subtree)
        """
        params: tuple = (skill_id,)
        if newest_first:
            query += " ORDER BY sessions.id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params = params + (limit,)

        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_session(r) for r in rows]

    def get_all_sessions(self) -> list[Session]:
        """
        Every session in the database, exactly once each, regardless of
        which skill (or group) it belongs to — the raw ground truth,
        with no group rollup applied. get_global_total_hours() is built
        on exactly this same idea internally.

        This is the right building block for anything (built-in or
        plugin) that needs to look at activity across the whole app —
        e.g. "everything logged today" — without double-counting a
        group member's hours once under its own name and again under
        its group, which is what get_sessions() would do if called
        per-skill across every skill including groups.
        """
        rows = self._conn.execute("SELECT * FROM sessions ORDER BY id DESC").fetchall()
        return [_row_to_session(r) for r in rows]

    def get_session_by_id(self, session_id: int) -> Session | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return _row_to_session(row) if row else None

    def delete_session(self, session_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # -- hours / totals --------------------------------------------------

    def get_total_hours(self, skill_name: str) -> float:
        skill = self.get_skill(skill_name)
        if skill is None:
            raise SkillNotFoundError(f'Skill "{skill_name}" does not exist')
        return _merge_interval_hours(self._fetch_subtree_sessions(skill.id))

    def get_global_total_hours(self) -> float:
        rows = self._conn.execute("SELECT * FROM sessions").fetchall()
        return _merge_interval_hours([_row_to_session(r) for r in rows])

    # -- background timers -------------------------------------------------

    def start_timer(self, skill_name: str) -> str:
        """Start a background timer for a skill. Returns started_at. Raises
        ValueError if one is already running for it."""
        skill = self.get_or_create_skill(skill_name)
        existing = self._timer_row(skill.id)
        if existing is not None:
            started_display = existing["started_at"].split(".")[0]
            raise ValueError(f'A timer for "{skill.name}" is already running (started {started_display}).')
        started_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO active_timers (skill_id, started_at, accumulated_seconds, resumed_at) VALUES (?, ?, 0, ?)",
            (skill.id, started_at, started_at),
        )
        self._conn.commit()
        return started_at

    def _timer_row(self, skill_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM active_timers WHERE skill_id = ?", (skill_id,)
        ).fetchone()

    def _elapsed_seconds(self, row: sqlite3.Row) -> float:
        elapsed = row["accumulated_seconds"]
        if row["resumed_at"] is not None:
            elapsed += (datetime.now(timezone.utc) - _parse_iso(row["resumed_at"])).total_seconds()
        return elapsed

    def get_active_timer(self, skill_name: str) -> str | None:
        """started_at if a timer is currently running for this skill, else None."""
        skill = self.get_skill(skill_name)
        if skill is None:
            return None
        row = self._timer_row(skill.id)
        return row["started_at"] if row else None

    def list_active_timers(self) -> list["ActiveTimerInfo"]:
        """Every currently-running (or paused) timer, oldest first."""
        rows = self._conn.execute(
            """SELECT skills.*, active_timers.started_at AS timer_started_at,
                      active_timers.accumulated_seconds AS timer_accumulated_seconds,
                      active_timers.resumed_at AS timer_resumed_at
               FROM active_timers
               JOIN skills ON skills.id = active_timers.skill_id
               ORDER BY active_timers.started_at ASC"""
        ).fetchall()
        result = []
        for r in rows:
            elapsed = r["timer_accumulated_seconds"]
            if r["timer_resumed_at"] is not None:
                elapsed += (datetime.now(timezone.utc) - _parse_iso(r["timer_resumed_at"])).total_seconds()
            result.append(
                ActiveTimerInfo(
                    skill=_row_to_skill(r),
                    started_at=r["timer_started_at"],
                    elapsed_seconds=elapsed,
                    is_paused=r["timer_resumed_at"] is None,
                )
            )
        return result

    def pause_timer(self, skill_name: str) -> None:
        """Pause a running background timer. No-op if it's already paused."""
        skill = self.get_skill(skill_name)
        row = self._timer_row(skill.id) if skill is not None else None
        if row is None:
            raise ValueError(f'No timer is running for "{skill_name}".')
        if row["resumed_at"] is None:
            return
        accumulated = row["accumulated_seconds"] + (
            datetime.now(timezone.utc) - _parse_iso(row["resumed_at"])
        ).total_seconds()
        self._conn.execute(
            "UPDATE active_timers SET accumulated_seconds = ?, resumed_at = NULL WHERE skill_id = ?",
            (accumulated, skill.id),
        )
        self._conn.commit()

    def resume_timer(self, skill_name: str) -> None:
        """Resume a paused background timer. No-op if it's already running."""
        skill = self.get_skill(skill_name)
        row = self._timer_row(skill.id) if skill is not None else None
        if row is None:
            raise ValueError(f'No timer is running for "{skill_name}".')
        if row["resumed_at"] is not None:
            return
        self._conn.execute(
            "UPDATE active_timers SET resumed_at = ? WHERE skill_id = ?",
            (datetime.now(timezone.utc).isoformat(), skill.id),
        )
        self._conn.commit()

    def stop_timer(self, skill_name: str) -> tuple[str, float]:
        """
        Stop a running (or paused) background timer. Returns (started_at,
        hours) for the caller to log as a session (kept separate from
        logging so the CLI can prompt for a note in between). Raises
        ValueError if no timer is running for this skill.
        """
        skill = self.get_skill(skill_name)
        row = self._timer_row(skill.id) if skill is not None else None
        if row is None:
            raise ValueError(f'No timer is running for "{skill_name}".')
        hours = self._elapsed_seconds(row) / 3600
        started_at = row["started_at"]
        self._conn.execute("DELETE FROM active_timers WHERE skill_id = ?", (skill.id,))
        self._conn.commit()
        return started_at, hours

    def cancel_timer(self, skill_name: str) -> None:
        """Abandon a running background timer without logging anything."""
        skill = self.get_skill(skill_name)
        row = self._timer_row(skill.id) if skill is not None else None
        if row is None:
            raise ValueError(f'No timer is running for "{skill_name}".')
        self._conn.execute("DELETE FROM active_timers WHERE skill_id = ?", (skill.id,))
        self._conn.commit()


def _row_to_skill(row: sqlite3.Row) -> Skill:
    return Skill(
        id=row["id"],
        name=row["name"],
        created_at=row["created_at"],
    )


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        skill_id=row["skill_id"],
        hours=row["hours"],
        note=row["note"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        logged_at=row["logged_at"],
    )