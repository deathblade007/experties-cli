import os
import time

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


def test_commands_lists_every_command(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("commands", db_path=db_path)
    assert result.exit_code == 0
    for name in ["list", "start", "log", "stats", "rank-table", "delete", "commands"]:
        assert name in result.output


def test_list_shows_division_in_rank_name(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "78h", db_path=db_path)
    result = _run("list", db_path=db_path)
    assert "Bronze 1" in result.output
    assert "Division 3" in result.output


def test_stats_shows_division_in_rank_name(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "78h", db_path=db_path)
    result = _run("stats", "Coding", db_path=db_path)
    assert "Division 3" in result.output


def test_list_progress_still_measures_full_rank_gap_not_division_gap(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "78h", db_path=db_path)
    result = _run("list", db_path=db_path)
    assert "5.0h" in result.output


def test_plugins_command_reports_no_plugins_when_dir_missing(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("plugins", db_path=db_path)
    assert result.exit_code == 0
    assert "No plugins loaded" in result.output or "Doesn't exist yet" in result.output


def test_commands_reference_includes_plugins(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("commands", db_path=db_path)
    assert "plugins" in result.output


def test_skill_rename_success(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "5h", db_path=db_path)
    result = _run("skill", "rename", "Coding", "Programming", db_path=db_path)
    assert result.exit_code == 0
    assert "Renamed" in result.output

    with Database(db_path) as db:
        assert db.get_skill("Coding") is None
        assert db.get_total_hours("Programming") == 5.0


def test_skill_rename_unknown_skill_errors(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("skill", "rename", "Nope", "Something", db_path=db_path)
    assert result.exit_code == 1
    assert "No skill named" in result.output


def test_skill_rename_to_existing_name_errors(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "1h", db_path=db_path)
    _run("log", "Guitar", "--time", "1h", db_path=db_path)
    result = _run("skill", "rename", "Coding", "Guitar", db_path=db_path)
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_skill_delete_with_yes_removes_skill_and_sessions(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "3h", db_path=db_path)
    result = _run("skill", "delete", "Coding", "--yes", db_path=db_path)
    assert result.exit_code == 0
    assert "Deleted" in result.output

    with Database(db_path) as db:
        assert db.get_skill("Coding") is None


def test_skill_delete_unknown_skill_errors(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("skill", "delete", "Nope", "--yes", db_path=db_path)
    assert result.exit_code == 1
    assert "No skill named" in result.output


def test_skill_delete_without_yes_can_be_declined(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "3h", db_path=db_path)
    result = _run("skill", "delete", "Coding", db_path=db_path, input="n\n")
    assert "Cancelled" in result.output

    with Database(db_path) as db:
        assert db.get_skill("Coding") is not None


# -- groups ---------------------------------------------------------------

def test_group_create_success(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("group", "create", "Machine Learning", db_path=db_path)
    assert result.exit_code == 0
    assert "Created group" in result.output


def test_group_create_duplicate_name_errors(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    result = _run("group", "create", "Machine Learning", db_path=db_path)
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_group_add_auto_creates_the_member_and_rolls_up_hours(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    _run("group", "add", "Machine Learning", "Maths", db_path=db_path)
    _run("log", "Python", "--time", "3h", db_path=db_path)
    _run("log", "Maths", "--time", "2h", db_path=db_path)

    with Database(db_path) as db:
        assert db.get_total_hours("Machine Learning") == 5.0


def test_group_add_auto_creates_an_unknown_group(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    assert result.exit_code == 0

    with Database(db_path) as db:
        assert db.get_skill("Machine Learning") is not None
        assert [s.name for s in db.get_group_members("Machine Learning")] == ["Python"]


def test_group_add_allows_nesting_a_group_inside_a_group(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "create", "Deep Learning", db_path=db_path)
    _run("group", "add", "Deep Learning", "PyTorch", db_path=db_path)
    result = _run("group", "add", "Machine Learning", "Deep Learning", db_path=db_path)
    assert result.exit_code == 0

    _run("log", "PyTorch", "--time", "4h", db_path=db_path)
    with Database(db_path) as db:
        assert db.get_total_hours("Machine Learning") == 4.0


def test_group_remove_ungroups_the_skill(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    result = _run("group", "remove", "Python", db_path=db_path)
    assert result.exit_code == 0
    assert "Removed" in result.output

    with Database(db_path) as db:
        assert db.get_group_of("Python") is None
        assert db.get_skill("Python") is not None


def test_group_remove_reports_when_not_in_a_group(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Python", "--time", "1h", db_path=db_path)
    result = _run("group", "remove", "Python", db_path=db_path)
    assert "wasn't in a group" in result.output


def test_group_list_shows_groups_and_members(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    result = _run("group", "list", db_path=db_path)
    assert "Machine Learning" in result.output
    assert "Python" in result.output


def test_group_list_with_no_groups_shows_hint(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("group", "list", db_path=db_path)
    assert "No groups yet" in result.output


def test_group_rename_success(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    _run("log", "Python", "--time", "3h", db_path=db_path)

    result = _run("group", "rename", "Machine Learning", "ML", db_path=db_path)
    assert result.exit_code == 0
    assert "Renamed" in result.output

    with Database(db_path) as db:
        assert db.get_skill("Machine Learning") is None
        renamed = db.get_skill("ML")
        assert renamed is not None
        assert db.get_total_hours("ML") == 3.0  # rollup survives the rename


def test_group_rename_also_works_on_a_plain_skill(tmp_path):
    # `group rename` is the same operation as `skill rename` now — every
    # skill can be a group, so there's no "must already be a group" gate.
    db_path = tmp_path / "data.db"
    _run("log", "Coding", "--time", "1h", db_path=db_path)
    result = _run("group", "rename", "Coding", "Programming", db_path=db_path)
    assert result.exit_code == 0
    with Database(db_path) as db:
        assert db.get_skill("Programming") is not None


def test_group_rename_unknown_group_errors(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("group", "rename", "Nope", "Something", db_path=db_path)
    assert result.exit_code == 1
    assert "No skill named" in result.output


def test_group_rename_to_existing_name_errors(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("log", "Guitar", "--time", "1h", db_path=db_path)
    result = _run("group", "rename", "Machine Learning", "Guitar", db_path=db_path)
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_group_rename_shows_up_in_group_list_afterward(tmp_path):
    # A group only "counts" for `group list` once it has a member — an
    # empty group renamed is still an empty group, so give it one first.
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    _run("group", "rename", "Machine Learning", "ML", db_path=db_path)
    result = _run("group", "list", db_path=db_path)
    assert "ML" in result.output
    assert "Machine Learning" not in result.output


# -- cd and list group-awareness -------------------------------------------

def test_cd_into_a_group_succeeds(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    result = _run("cd", "Machine Learning", db_path=db_path)
    assert result.exit_code == 0
    assert "Now focused" in result.output


def test_cd_into_any_existing_skill_succeeds(tmp_path):
    # cd no longer requires the target to already have members — every
    # skill can become a group, so you can cd into one before it has any.
    db_path = tmp_path / "data.db"
    _run("log", "Python", "--time", "1h", db_path=db_path)
    result = _run("cd", "Python", db_path=db_path)
    assert result.exit_code == 0
    assert "Now focused" in result.output


def test_cd_into_unknown_skill_errors(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("cd", "Nope", db_path=db_path)
    assert result.exit_code == 1
    assert "No skill named" in result.output


def test_cd_with_no_args_goes_back_to_top_level(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("cd", "Machine Learning", db_path=db_path)
    result = _run("cd", db_path=db_path)
    assert "top level" in result.output


def test_list_at_top_level_shows_group_members_nested(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    _run("group", "add", "Machine Learning", "Maths", db_path=db_path)
    _run("log", "Python", "--time", "3h", db_path=db_path)
    _run("log", "Maths", "--time", "2h", db_path=db_path)
    _run("log", "Guitar", "--time", "1h", db_path=db_path)

    result = _run("list", db_path=db_path)
    assert "Machine Learning" in result.output
    assert "Guitar" in result.output
    assert "Python" in result.output
    assert "Maths" in result.output
    assert "5.0h" in result.output


def test_list_at_top_level_shows_empty_group_like_any_other_skill(tmp_path):
    # An empty group has no members yet, so it isn't "a group" in any
    # visible way until something is nested under it — it just shows up
    # as a normal 0h row, same as any freshly-created skill would.
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("log", "Guitar", "--time", "1h", db_path=db_path)

    result = _run("list", db_path=db_path)
    assert "Machine Learning" in result.output
    assert "no members yet" not in result.output


def test_list_at_top_level_nests_groups_inside_groups(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Deep Learning", db_path=db_path)
    _run("group", "add", "Deep Learning", "PyTorch", db_path=db_path)
    _run("log", "PyTorch", "--time", "4h", db_path=db_path)

    result = _run("list", db_path=db_path)
    assert "Machine Learning" in result.output
    assert "Deep Learning" in result.output
    assert "PyTorch" in result.output
    assert "4.0h" in result.output  # rolled all the way up to Machine Learning


def test_list_after_cd_shows_group_members(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    _run("group", "add", "Machine Learning", "Maths", db_path=db_path)
    _run("cd", "Machine Learning", db_path=db_path)

    result = _run("list", db_path=db_path)
    assert "Python" in result.output
    assert "Maths" in result.output
    assert "Inside" in result.output


def test_list_falls_back_gracefully_if_cd_group_was_deleted(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("cd", "Machine Learning", db_path=db_path)
    _run("skill", "delete", "Machine Learning", "--yes", db_path=db_path)

    result = _run("list", db_path=db_path)
    assert result.exit_code == 0


def test_global_total_not_inflated_by_grouping_through_the_real_cli(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    _run("log", "Python", "--time", "3h", db_path=db_path)
    _run("log", "Guitar", "--time", "2h", db_path=db_path)

    with Database(db_path) as db:
        assert db.get_global_total_hours() == 5.0


def test_stats_on_group_shows_skill_column(tmp_path):
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    _run("log", "Python", "--time", "3h", "--note", "numpy", db_path=db_path)

    result = _run("stats", "Machine Learning", db_path=db_path)
    assert "Skill" in result.output
    assert "Python" in result.output
    assert "numpy" in result.output


def test_stats_on_regular_skill_has_no_skill_column(tmp_path):
    db_path = tmp_path / "data.db"
    _run("log", "Python", "--time", "1h", db_path=db_path)
    result = _run("stats", "Python", db_path=db_path)
    assert "┃ Skill" not in result.output


# -- background timers ------------------------------------------------------

def test_timer_start_then_status_shows_it_running(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("timer", "start", "Python", db_path=db_path)
    assert result.exit_code == 0
    assert "Timer started" in result.output

    status = _run("timer", "status", db_path=db_path)
    assert "Python" in status.output


def test_timer_start_twice_for_same_skill_errors(tmp_path):
    db_path = tmp_path / "data.db"
    _run("timer", "start", "Python", db_path=db_path)
    result = _run("timer", "start", "Python", db_path=db_path)
    assert result.exit_code == 1
    assert "already running" in result.output


def test_timer_start_two_different_skills_both_show_in_status(tmp_path):
    db_path = tmp_path / "data.db"
    _run("timer", "start", "Python", db_path=db_path)
    _run("timer", "start", "Maths", db_path=db_path)
    status = _run("timer", "status", db_path=db_path)
    assert "Python" in status.output
    assert "Maths" in status.output


def test_timer_status_with_nothing_running_shows_hint(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("timer", "status", db_path=db_path)
    assert "No timers running" in result.output


def test_timer_stop_logs_a_session(tmp_path):
    db_path = tmp_path / "data.db"
    _run("timer", "start", "Python", db_path=db_path)
    result = _run("timer", "stop", "Python", db_path=db_path, input="\n")
    assert result.exit_code == 0
    assert "Logged" in result.output

    with Database(db_path) as db:
        assert db.get_active_timer("Python") is None
        assert db.get_total_hours("Python") > 0


def test_timer_stop_with_nothing_running_errors(tmp_path):
    db_path = tmp_path / "data.db"
    result = _run("timer", "stop", "Python", db_path=db_path, input="\n")
    assert result.exit_code == 1
    assert "No timer is running" in result.output


def test_timer_cancel_logs_nothing(tmp_path):
    db_path = tmp_path / "data.db"
    _run("timer", "start", "Python", db_path=db_path)
    result = _run("timer", "cancel", "Python", db_path=db_path)
    assert result.exit_code == 0
    assert "cancelled" in result.output

    with Database(db_path) as db:
        assert db.get_active_timer("Python") is None
        assert db.get_total_hours("Python") == 0.0


def test_two_concurrent_group_timers_count_the_overlap_once_in_the_group_total(tmp_path):
    # This is the actual scenario that was asked for: start two members of
    # the same group at once, stop them, and confirm the group's total
    # doesn't double the overlapping time.
    db_path = tmp_path / "data.db"
    _run("group", "create", "Machine Learning", db_path=db_path)
    _run("group", "add", "Machine Learning", "Python", db_path=db_path)
    _run("group", "add", "Machine Learning", "Maths", db_path=db_path)

    _run("timer", "start", "Python", db_path=db_path)
    _run("timer", "start", "Maths", db_path=db_path)
    time.sleep(0.05)
    _run("timer", "stop", "Python", db_path=db_path, input="\n")
    _run("timer", "stop", "Maths", db_path=db_path, input="\n")

    with Database(db_path) as db:
        python_hours = db.get_total_hours("Python")
        maths_hours = db.get_total_hours("Maths")
        group_hours = db.get_total_hours("Machine Learning")
        global_hours = db.get_global_total_hours()

        # Both ran essentially the whole window concurrently, so the
        # group's total should be close to just one of them, not their sum.
        assert group_hours < (python_hours + maths_hours) * 0.9
        assert global_hours == group_hours