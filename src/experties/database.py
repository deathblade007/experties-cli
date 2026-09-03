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

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id   INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    hours      REAL NOT NULL CHECK (hours > 0),
    note       TEXT,
    started_at TEXT,
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
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    logged_at: str


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
        self._conn.commit()

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
            ORDER BY sessions.id DESC
        """
        params: tuple = (skill.id,)
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

        row = self._conn.execute(
            """
            WITH RECURSIVE subtree(id) AS (
                SELECT ?
                UNION ALL
                SELECT skill_groups.child_skill_id
                FROM skill_groups
                JOIN subtree ON skill_groups.parent_skill_id = subtree.id
            )
            SELECT COALESCE(SUM(sessions.hours), 0) AS total FROM sessions
            WHERE sessions.skill_id IN (SELECT id FROM subtree)
            """,
            (skill.id,),
        ).fetchone()
        return row["total"]

    def get_global_total_hours(self) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(hours), 0) AS total FROM sessions"
        ).fetchone()
        return row["total"]


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
        logged_at=row["logged_at"],
    )