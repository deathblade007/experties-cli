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

    def get_or_create_skill(self, name: str) -> Skill:
        return self.get_skill(name) or self.add_skill(name)

    def list_skills(self) -> list[Skill]:
        rows = self._conn.execute(
            "SELECT * FROM skills ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

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
