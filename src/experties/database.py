"""
Local SQLite storage for Experties-CLI.

Every skill and every logged session lives in a single SQLite file at
~/.experties/data.db by default. There's no server and no network calls —
this module is the entire persistence layer.

A "session" here always means a committed, already-finished chunk of time
(hours > 0) attached to a skill. Both the live timer (timer.py) and manual
logging (`experties log`) go through the same log_session() call — the
schema doesn't care whether the hours came from a stopwatch or were typed
in by hand.

The Database class holds a single open connection for its lifetime rather
than reconnecting per call. This isn't just an optimization: it's required
for ":memory:" databases to work at all (each fresh connection to
":memory:" otherwise gets its own empty database), and it's what lets
tests use Database(":memory:") cleanly.
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
    created_at TEXT NOT NULL,
    is_group   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id   INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    hours      REAL NOT NULL CHECK (hours > 0),
    note       TEXT,
    started_at TEXT,
    logged_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_skill_id ON sessions(skill_id);

-- A skill belongs to at most one group, enforced by child_skill_id
-- being the primary key (not just unique) — one row per possible child.
-- No nesting: a group's members are always regular skills, checked in
-- application code (add_to_group), not by the schema itself.
CREATE TABLE IF NOT EXISTS skill_groups (
    child_skill_id  INTEGER PRIMARY KEY REFERENCES skills(id) ON DELETE CASCADE,
    parent_skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Skill:
    id: int
    name: str
    created_at: str
    is_group: bool = False


@dataclass(frozen=True)
class Session:
    id: int
    skill_id: int
    hours: float
    note: str | None
    started_at: str | None
    logged_at: str


class SkillAlreadyExistsError(Exception):
    pass


class SkillNotFoundError(Exception):
    pass


class Database:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            # Lets the CLI and tests point at a different file (or an
            # in-memory DB) without changing any calling code — set
            # EXPERTIES_DB_PATH before invoking `experties`.
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
        self._migrate_add_is_group_column()
        self._conn.commit()

    def _migrate_add_is_group_column(self) -> None:
        """
        Existing databases created before groups existed have a `skills`
        table with no `is_group` column — CREATE TABLE IF NOT EXISTS in
        _SCHEMA is a no-op against a table that already exists, so it
        can't retroactively add a column on its own. This runs on every
        startup, checks whether the column is actually there via SQLite's
        own introspection, and adds it exactly once if not. Safe to run
        against a brand-new database too — is_group will already exist
        from _SCHEMA, so this becomes a no-op in that case.
        """
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(skills)")}
        if "is_group" not in columns:
            self._conn.execute("ALTER TABLE skills ADD COLUMN is_group INTEGER NOT NULL DEFAULT 0")

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
        Create a new skill marked as a group — a "super skill" whose
        total hours (via get_total_hours) automatically include every
        member added with add_to_group, on top of any hours logged
        directly to the group itself. Raises SkillAlreadyExistsError if
        a skill with this name already exists, group or not.
        """
        name = name.strip()
        if not name:
            raise ValueError("group name cannot be empty")

        if self.get_skill(name) is not None:
            raise SkillAlreadyExistsError(f'Skill "{name}" already exists')

        created_at = _now_iso()
        cur = self._conn.execute(
            "INSERT INTO skills (name, created_at, is_group) VALUES (?, ?, 1)",
            (name, created_at),
        )
        self._conn.commit()
        return Skill(id=cur.lastrowid, name=name, created_at=created_at, is_group=True)

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

    def list_skills(self) -> list[Skill]:
        rows = self._conn.execute(
            "SELECT * FROM skills ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def list_groups(self) -> list[Skill]:
        """Every skill marked as a group, name order."""
        rows = self._conn.execute(
            "SELECT * FROM skills WHERE is_group = 1 ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def get_ungrouped_skills(self) -> list[Skill]:
        """Skills that are neither a group nor a member of one — the
        top-level `experties list` view shows these plus every group."""
        rows = self._conn.execute(
            """SELECT skills.* FROM skills
               WHERE skills.is_group = 0
                 AND skills.id NOT IN (SELECT child_skill_id FROM skill_groups)
               ORDER BY skills.name COLLATE NOCASE"""
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def get_top_level_skills_with_hours(self) -> list[tuple[Skill, float]]:
        """Every group (with its rolled-up total) plus every ungrouped
        skill — what `experties list` shows when no group is currently
        focused via `experties cd`."""
        top_level = self.list_groups() + self.get_ungrouped_skills()
        top_level.sort(key=lambda s: s.name.lower())
        return [(skill, self.get_total_hours(skill.name)) for skill in top_level]

    def add_to_group(self, group_name: str, skill_name: str) -> Skill:
        """
        Add skill_name as a member of group_name. skill_name is
        auto-created if it doesn't exist yet, same convenience as
        log_session. Returns the member skill.

        Raises SkillNotFoundError if group_name doesn't exist or isn't
        actually a group. Raises ValueError if skill_name is itself a
        group (no nesting), is the group itself, or already belongs to
        a different group — remove it from that one first.
        """
        group = self.get_skill(group_name)
        if group is None or not group.is_group:
            raise SkillNotFoundError(
                f'"{group_name}" is not a group. Create it first with `experties group create`.'
            )

        skill = self.get_or_create_skill(skill_name)
        if skill.id == group.id:
            raise ValueError("a group can't contain itself")
        if skill.is_group:
            raise ValueError(f'"{skill.name}" is itself a group — groups can\'t be nested.')

        current_parent = self.get_group_of(skill.name)
        if current_parent is not None and current_parent.id != group.id:
            raise ValueError(f'"{skill.name}" already belongs to the group "{current_parent.name}".')

        self._conn.execute(
            "INSERT OR REPLACE INTO skill_groups (child_skill_id, parent_skill_id) VALUES (?, ?)",
            (skill.id, group.id),
        )
        self._conn.commit()
        return skill

    def remove_from_group(self, skill_name: str) -> bool:
        """Remove skill_name from whatever group it belongs to — the
        skill itself is untouched, only ungrouped. Returns True if it
        was in a group, False if it wasn't (not an error either way)."""
        skill = self.get_skill(skill_name)
        if skill is None:
            raise SkillNotFoundError(f'Skill "{skill_name}" does not exist')
        cur = self._conn.execute("DELETE FROM skill_groups WHERE child_skill_id = ?", (skill.id,))
        self._conn.commit()
        return cur.rowcount > 0

    def get_group_members(self, group_name: str) -> list[Skill]:
        """Skills belonging to a group, name order."""
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

    def get_group_of(self, skill_name: str) -> Skill | None:
        """The group a skill belongs to, or None if it's ungrouped (or
        doesn't exist — that's not this method's job to check)."""
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
        """
        Rename a skill in place — its id and all its sessions are
        unaffected, so its full history moves with the new name.

        Renaming to the same name with different casing (e.g. "coding"
        -> "Coding") is allowed. Renaming to a name already used by a
        DIFFERENT skill raises SkillAlreadyExistsError, same as add_skill.
        """
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
        return Skill(id=skill.id, name=new_name, created_at=skill.created_at, is_group=skill.is_group)

    def delete_skill(self, name: str) -> bool:
        """
        Delete a skill and every session logged against it. Returns True
        if the skill existed and was removed, False if there was no such
        skill.

        This is the one place ON DELETE CASCADE (set up in the schema,
        enforced via PRAGMA foreign_keys = ON in __init__) actually
        matters — unlike delete_session(), which only ever removes one
        session and never touches the skill it belongs to, this takes
        the skill's entire history with it. There's no undo.
        """
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
            """INSERT INTO sessions (skill_id, hours, note, started_at, logged_at)
               VALUES (?, ?, ?, ?, ?)""",
            (skill.id, hours, note, started_at, logged_at),
        )
        self._conn.commit()
        return Session(
            id=cur.lastrowid,
            skill_id=skill.id,
            hours=hours,
            note=note,
            started_at=started_at,
            logged_at=logged_at,
        )

    def get_sessions(self, skill_name: str, limit: int | None = None) -> list[Session]:
        skill = self.get_skill(skill_name)
        if skill is None:
            raise SkillNotFoundError(f'Skill "{skill_name}" does not exist')

        # Ordered by id (not logged_at) so insertion order stays unambiguous
        # even when two sessions are logged within the same second. For a
        # group, this merges its own direct sessions with every member's
        # sessions, interleaved by recency — not just the group's own.
        if skill.is_group:
            query = """SELECT * FROM sessions
                       WHERE skill_id = ?
                          OR skill_id IN (SELECT child_skill_id FROM skill_groups WHERE parent_skill_id = ?)
                       ORDER BY id DESC"""
            params: tuple = (skill.id, skill.id)
        else:
            query = "SELECT * FROM sessions WHERE skill_id = ? ORDER BY id DESC"
            params = (skill.id,)

        if limit is not None:
            query += " LIMIT ?"
            params = params + (limit,)

        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_session(r) for r in rows]

    def get_session_by_id(self, session_id: int) -> Session | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return _row_to_session(row) if row else None

    def delete_session(self, session_id: int) -> bool:
        """Delete one session by id. Returns True if a row was removed,
        False if no session with that id existed. Deleting a session never
        deletes the skill itself, even if it was the skill's only session —
        the skill just goes back to however many hours are left (possibly 0)."""
        cur = self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # -- hours / totals --------------------------------------------------

    def get_total_hours(self, skill_name: str) -> float:
        skill = self.get_skill(skill_name)
        if skill is None:
            raise SkillNotFoundError(f'Skill "{skill_name}" does not exist')

        if skill.is_group:
            # Own direct sessions (if any were logged straight to the
            # group) plus every member's sessions — single source of
            # truth for a group's hours, so stats/rank/list all agree
            # automatically without each needing their own rollup logic.
            row = self._conn.execute(
                """SELECT COALESCE(SUM(hours), 0) AS total FROM sessions
                   WHERE skill_id = ?
                      OR skill_id IN (SELECT child_skill_id FROM skill_groups WHERE parent_skill_id = ?)""",
                (skill.id, skill.id),
            ).fetchone()
            return row["total"]

        row = self._conn.execute(
            "SELECT COALESCE(SUM(hours), 0) AS total FROM sessions WHERE skill_id = ?",
            (skill.id,),
        ).fetchone()
        return row["total"]

    def get_global_total_hours(self) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(hours), 0) AS total FROM sessions"
        ).fetchone()
        return row["total"]

    def get_all_skills_with_hours(self) -> list[tuple[Skill, float]]:
        rows = self._conn.execute(
            """
            SELECT skills.*, COALESCE(SUM(sessions.hours), 0) AS total_hours
            FROM skills
            LEFT JOIN sessions ON sessions.skill_id = skills.id
            GROUP BY skills.id
            ORDER BY skills.name COLLATE NOCASE
            """
        ).fetchall()
        return [(_row_to_skill(r), r["total_hours"]) for r in rows]


def _row_to_skill(row: sqlite3.Row) -> Skill:
    return Skill(
        id=row["id"],
        name=row["name"],
        created_at=row["created_at"],
        is_group=bool(row["is_group"]),
    )


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        skill_id=row["skill_id"],
        hours=row["hours"],
        note=row["note"],
        started_at=row["started_at"],
        logged_at=row["logged_at"],
    )