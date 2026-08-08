"""
End-to-end CLI tests, run through Typer's CliRunner against the real
commands. Each test points EXPERTIES_DB_PATH at a pytest tmp_path so
nothing ever touches the real ~/.experties data.
"""

import os

from typer.testing import CliRunner

from experties.cli import app
from experties.database import Database

runner = CliRunner()


def _run(*args, db_path, input=None):
    env = os.environ.copy()
    env["EXPERTIES_DB_PATH"] = str(db_path)
    return runner.invoke(app, list(args), env=env, input=input)


def test_list_with_no_skills_shows_hint(tmp_path):
    result = _run("list", db_path=tmp_path / "data.db")
    assert result.exit_code == 0
    assert "No skills yet" in result.output


def test_log_then_list_shows_the_skill(tmp_path):
    db_path = tmp_path / "data.db"
    log_result = _run("log", "Coding", "--time", "20h", db_path=db_path)
    assert log_result.exit_code == 0
    assert "Logged 20.00h" in log_result.output

    list_result = _run("list", db_path=db_path)
    assert list_result.exit_code == 0
    assert "Coding" in list_result.output
    assert "Mud 2" in list_result.output


def test_log_reports_level_up(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("log", "Coding", "--time", "16h", db_path=db_path)
    assert result.exit_code == 0
    assert "LEVEL UP" in result.output
    assert "Mud 1" in result.output


def test_log_does_not_report_level_up_when_still_in_same_tier(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "16h", db_path=db_path)
    result = _run("log", "Coding", "--time", "1h", db_path=db_path)
    assert "LEVEL UP" not in result.output


def test_log_rejects_bad_duration(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("log", "Coding", "--time", "notaduration", db_path=db_path)
    assert result.exit_code == 1
    assert "Could not parse duration" in result.output


def test_stats_for_unknown_skill_errors_cleanly(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("stats", "Nope", db_path=db_path)
    assert result.exit_code == 1
    assert "No skill named" in result.output


def test_stats_shows_recent_sessions(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "1h", "--note", "warmup", db_path=db_path)
    result = _run("stats", "Coding", db_path=db_path)
    assert result.exit_code == 0
    assert "warmup" in result.output


def test_rank_table_runs_and_lists_tiers(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("rank-table", db_path=db_path)
    assert result.exit_code == 0
    assert "Unranked" in result.output
    assert "Grand Champion 3" in result.output


def test_delete_with_yes_flag_removes_session(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "1h", db_path=db_path)
    with Database(db_path) as db:
        session_id = db.get_sessions("Coding")[0].id

    result = _run("delete", str(session_id), "--yes", db_path=db_path)
    assert result.exit_code == 0
    assert "Deleted session" in result.output

    with Database(db_path) as db:
        assert db.get_total_hours("Coding") == 0.0


def test_delete_unknown_id_errors(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("delete", "999", "--yes", db_path=db_path)
    assert result.exit_code == 1
    assert "No session with id" in result.output


def test_delete_without_yes_prompts_and_can_be_declined(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "1h", db_path=db_path)
    with Database(db_path) as db:
        session_id = db.get_sessions("Coding")[0].id

    result = _run("delete", str(session_id), db_path=db_path, input="n\n")
    assert "Cancelled" in result.output

    with Database(db_path) as db:
        assert db.get_total_hours("Coding") == 1.0
