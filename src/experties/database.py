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
            # Lets the CLI and tests point at a different file (or an
            # in-memory DB) without changing any calling code — set
            # EXPERTIES_DB_PATH before invoking `experties`.
            db_path = os.environ.get("EXPERTIES_DB_PATH") or DEFAULT_DB_PATH

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
        return Skill(id=skill.id, name=new_name, created_at=skill.created_at)

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
        # even when two sessions are logged within the same second.
        query = "SELECT * FROM sessions WHERE skill_id = ? ORDER BY id DESC"
        params: tuple = (skill.id,)
        if limit is not None:
            query += " LIMIT ?"
            params = (skill.id, limit)

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
    return Skill(id=row["id"], name=row["name"], created_at=row["created_at"])


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        skill_id=row["skill_id"],
        hours=row["hours"],
        note=row["note"],
        started_at=row["started_at"],
        logged_at=row["logged_at"],
    )