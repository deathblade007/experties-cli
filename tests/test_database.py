import pytest

from experties.database import Database, SkillAlreadyExistsError, SkillNotFoundError


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


def test_add_skill_creates_it(db):
    skill = db.add_skill("Coding")
    assert skill.name == "Coding"
    assert skill.id is not None


def test_add_duplicate_skill_raises(db):
    db.add_skill("Coding")
    with pytest.raises(SkillAlreadyExistsError):
        db.add_skill("Coding")


def test_add_duplicate_skill_is_case_insensitive(db):
    db.add_skill("Coding")
    with pytest.raises(SkillAlreadyExistsError):
        db.add_skill("coding")


def test_add_skill_rejects_empty_name(db):
    with pytest.raises(ValueError):
        db.add_skill("   ")


def test_get_skill_returns_none_when_missing(db):
    assert db.get_skill("Nope") is None


def test_get_or_create_skill_only_creates_once(db):
    first = db.get_or_create_skill("Guitar")
    second = db.get_or_create_skill("Guitar")
    assert first.id == second.id
    assert len(db.list_skills()) == 1


def test_list_skills_sorted_by_name(db):
    db.add_skill("Zeta")
    db.add_skill("Alpha")
    assert [s.name for s in db.list_skills()] == ["Alpha", "Zeta"]


def test_log_session_auto_creates_skill_by_default(db):
    db.log_session("Coding", 1.5)
    assert db.get_skill("Coding") is not None
    assert db.get_total_hours("Coding") == 1.5


def test_log_session_without_auto_create_raises_if_missing(db):
    with pytest.raises(SkillNotFoundError):
        db.log_session("Coding", 1.0, create_skill_if_missing=False)


def test_log_session_rejects_non_positive_hours(db):
    with pytest.raises(ValueError):
        db.log_session("Coding", 0)
    with pytest.raises(ValueError):
        db.log_session("Coding", -2)


def test_total_hours_accumulates_across_sessions(db):
    db.log_session("Coding", 1.0)
    db.log_session("Coding", 2.5)
    assert db.get_total_hours("Coding") == 3.5


def test_total_hours_raises_for_unknown_skill(db):
    with pytest.raises(SkillNotFoundError):
        db.get_total_hours("Nope")


def test_global_total_sums_across_all_skills(db):
    db.log_session("Coding", 2.0)
    db.log_session("Guitar", 1.0)
    assert db.get_global_total_hours() == 3.0


def test_all_skills_with_hours_includes_zero_hour_skills(db):
    db.add_skill("Untouched")
    db.log_session("Coding", 4.0)
    results = {skill.name: hours for skill, hours in db.get_all_skills_with_hours()}
    assert results["Untouched"] == 0.0
    assert results["Coding"] == 4.0


def test_get_sessions_ordered_most_recent_first(db):
    db.log_session("Coding", 1.0, note="first")
    db.log_session("Coding", 2.0, note="second")
    sessions = db.get_sessions("Coding")
    assert [s.note for s in sessions] == ["second", "first"]


def test_get_sessions_respects_limit(db):
    for _ in range(5):
        db.log_session("Coding", 1.0)
    assert len(db.get_sessions("Coding", limit=2)) == 2


def test_get_sessions_raises_for_unknown_skill(db):
    with pytest.raises(SkillNotFoundError):
        db.get_sessions("Nope")


def test_note_is_stripped_and_blank_becomes_none(db):
    session = db.log_session("Coding", 1.0, note="   ")
    assert session.note is None
    session2 = db.log_session("Coding", 1.0, note="  solved a bug  ")
    assert session2.note == "solved a bug"


def test_get_session_by_id_returns_none_when_missing(db):
    assert db.get_session_by_id(999) is None


def test_get_session_by_id_returns_the_session(db):
    logged = db.log_session("Coding", 1.5, note="warmup")
    fetched = db.get_session_by_id(logged.id)
    assert fetched == logged


def test_delete_session_removes_it_and_returns_true(db):
    session = db.log_session("Coding", 2.0)
    assert db.delete_session(session.id) is True
    assert db.get_session_by_id(session.id) is None
    assert db.get_total_hours("Coding") == 0.0


def test_delete_session_returns_false_for_unknown_id(db):
    assert db.delete_session(999) is False


def test_delete_session_does_not_delete_the_skill(db):
    session = db.log_session("Coding", 2.0)
    db.delete_session(session.id)
    assert db.get_skill("Coding") is not None


def test_rename_skill_changes_the_name(db):
    db.log_session("Coding", 5.0)
    renamed = db.rename_skill("Coding", "Programming")
    assert renamed.name == "Programming"
    assert db.get_skill("Coding") is None
    assert db.get_skill("Programming") is not None


def test_rename_skill_preserves_history(db):
    db.log_session("Coding", 3.0)
    db.log_session("Coding", 2.0)
    renamed = db.rename_skill("Coding", "Programming")
    assert db.get_total_hours("Programming") == 5.0
    assert len(db.get_sessions("Programming")) == 2


def test_rename_skill_raises_for_unknown_old_name(db):
    with pytest.raises(SkillNotFoundError):
        db.rename_skill("Nope", "Something")


def test_rename_skill_raises_if_new_name_taken_by_different_skill(db):
    db.add_skill("Coding")
    db.add_skill("Guitar")
    with pytest.raises(SkillAlreadyExistsError):
        db.rename_skill("Coding", "Guitar")


def test_rename_skill_allows_case_only_change_of_its_own_name(db):
    db.add_skill("coding")
    renamed = db.rename_skill("coding", "Coding")
    assert renamed.name == "Coding"


def test_rename_skill_rejects_empty_new_name(db):
    db.add_skill("Coding")
    with pytest.raises(ValueError):
        db.rename_skill("Coding", "   ")


def test_rename_skill_preserves_is_group(db):
    db.create_group("Machine Learning")
    renamed = db.rename_skill("Machine Learning", "ML")
    assert renamed.is_group is True
    assert db.get_skill("ML").is_group is True


def test_delete_skill_removes_it_and_returns_true(db):
    db.add_skill("Coding")
    assert db.delete_skill("Coding") is True
    assert db.get_skill("Coding") is None


def test_delete_skill_returns_false_for_unknown_skill(db):
    assert db.delete_skill("Nope") is False


def test_delete_skill_cascades_to_its_sessions(db):
    db.log_session("Coding", 3.0)
    db.log_session("Coding", 2.0)
    db.delete_skill("Coding")
    row = db._conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()
    assert row["n"] == 0


def test_delete_skill_does_not_affect_other_skills(db):
    db.log_session("Coding", 3.0)
    db.log_session("Guitar", 4.0)
    db.delete_skill("Coding")
    assert db.get_skill("Guitar") is not None
    assert db.get_total_hours("Guitar") == 4.0


# -- groups -------------------------------------------------------------

def test_create_group_marks_it_as_a_group(db):
    group = db.create_group("Machine Learning")
    assert group.is_group is True


def test_create_group_rejects_duplicate_name(db):
    db.create_group("Machine Learning")
    with pytest.raises(SkillAlreadyExistsError):
        db.create_group("Machine Learning")


def test_create_group_rejects_empty_name(db):
    with pytest.raises(ValueError):
        db.create_group("   ")


def test_add_to_group_auto_creates_the_member_skill(db):
    db.create_group("Machine Learning")
    member = db.add_to_group("Machine Learning", "Python")
    assert member.name == "Python"
    assert db.get_skill("Python") is not None


def test_add_to_group_rejects_unknown_group(db):
    with pytest.raises(SkillNotFoundError):
        db.add_to_group("Not A Group", "Python")


def test_add_to_group_rejects_non_group_skill_as_target(db):
    db.add_skill("Coding")
    with pytest.raises(SkillNotFoundError):
        db.add_to_group("Coding", "Python")


def test_add_to_group_rejects_nesting_a_group(db):
    db.create_group("Machine Learning")
    db.create_group("Programming")
    with pytest.raises(ValueError):
        db.add_to_group("Machine Learning", "Programming")


def test_add_to_group_rejects_group_containing_itself(db):
    db.create_group("Machine Learning")
    with pytest.raises(ValueError):
        db.add_to_group("Machine Learning", "Machine Learning")


def test_add_to_group_rejects_skill_already_in_a_different_group(db):
    db.create_group("Machine Learning")
    db.create_group("Web Dev")
    db.add_to_group("Machine Learning", "Python")
    with pytest.raises(ValueError):
        db.add_to_group("Web Dev", "Python")


def test_add_to_group_is_idempotent_for_the_same_group(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.add_to_group("Machine Learning", "Python")
    assert len(db.get_group_members("Machine Learning")) == 1


def test_remove_from_group_ungroups_but_keeps_the_skill(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    assert db.remove_from_group("Python") is True
    assert db.get_skill("Python") is not None
    assert db.get_group_of("Python") is None


def test_remove_from_group_returns_false_if_not_in_a_group(db):
    db.add_skill("Python")
    assert db.remove_from_group("Python") is False


def test_remove_from_group_raises_for_unknown_skill(db):
    with pytest.raises(SkillNotFoundError):
        db.remove_from_group("Nope")


def test_get_group_members_lists_them_in_name_order(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.add_to_group("Machine Learning", "Maths")
    names = [s.name for s in db.get_group_members("Machine Learning")]
    assert names == ["Maths", "Python"]


def test_get_group_of_returns_the_parent(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    parent = db.get_group_of("Python")
    assert parent is not None
    assert parent.name == "Machine Learning"


def test_get_group_of_returns_none_for_ungrouped_skill(db):
    db.add_skill("Coding")
    assert db.get_group_of("Coding") is None


def test_list_groups_returns_only_groups(db):
    db.create_group("Machine Learning")
    db.add_skill("Coding")
    names = [s.name for s in db.list_groups()]
    assert names == ["Machine Learning"]


def test_get_ungrouped_skills_excludes_groups_and_members(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.add_skill("Guitar")
    names = [s.name for s in db.get_ungrouped_skills()]
    assert names == ["Guitar"]


def test_group_total_hours_rolls_up_its_members(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.add_to_group("Machine Learning", "Maths")
    db.log_session("Python", 3.0)
    db.log_session("Maths", 2.0)
    assert db.get_total_hours("Machine Learning") == 5.0
    assert db.get_total_hours("Python") == 3.0
    assert db.get_total_hours("Maths") == 2.0


def test_group_total_hours_also_includes_its_own_direct_sessions(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.log_session("Python", 3.0)
    db.log_session("Machine Learning", 1.0)
    assert db.get_total_hours("Machine Learning") == 4.0


def test_group_sessions_merge_own_and_members_sorted_by_recency(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.add_to_group("Machine Learning", "Maths")
    db.log_session("Python", 1.0, note="python session")
    db.log_session("Maths", 1.0, note="maths session")
    db.log_session("Machine Learning", 1.0, note="direct ml session")

    sessions = db.get_sessions("Machine Learning")
    assert len(sessions) == 3
    assert [s.note for s in sessions] == ["direct ml session", "maths session", "python session"]


def test_global_total_is_not_double_counted_by_grouping(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.log_session("Python", 3.0)
    db.log_session("Guitar", 2.0)
    assert db.get_global_total_hours() == 5.0


def test_get_top_level_skills_with_hours_shows_groups_not_members(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.add_to_group("Machine Learning", "Maths")
    db.log_session("Python", 3.0)
    db.log_session("Maths", 2.0)
    db.add_skill("Guitar")
    db.log_session("Guitar", 1.0)

    top_level = db.get_top_level_skills_with_hours()
    names_and_hours = {s.name: h for s, h in top_level}

    assert names_and_hours == {"Machine Learning": 5.0, "Guitar": 1.0}
    assert "Python" not in names_and_hours
    assert "Maths" not in names_and_hours


def test_delete_group_does_not_delete_its_members(db):
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.log_session("Python", 3.0)
    db.delete_skill("Machine Learning")
    assert db.get_skill("Python") is not None
    assert db.get_total_hours("Python") == 3.0
    assert db.get_group_of("Python") is None


# -- get_all_sessions -----------------------------------------------------

def test_get_all_sessions_returns_every_session_exactly_once(db):
    db.log_session("Coding", 1.0)
    db.log_session("Guitar", 2.0)
    db.log_session("Coding", 0.5)
    assert len(db.get_all_sessions()) == 3


def test_get_all_sessions_is_not_inflated_by_grouping(db):
    # This is the property that matters most: a group member's session
    # must appear exactly once in get_all_sessions(), never twice just
    # because it also happens to roll up into a group.
    db.create_group("Machine Learning")
    db.add_to_group("Machine Learning", "Python")
    db.log_session("Python", 3.0)
    db.log_session("Machine Learning", 1.0)
    db.log_session("Guitar", 2.0)

    all_sessions = db.get_all_sessions()
    assert len(all_sessions) == 3
    assert sum(s.hours for s in all_sessions) == 6.0


def test_get_all_sessions_ordered_most_recent_first(db):
    db.log_session("Coding", 1.0, note="first")
    db.log_session("Coding", 2.0, note="second")
    sessions = db.get_all_sessions()
    assert [s.note for s in sessions] == ["second", "first"]


def test_get_all_sessions_empty_database(db):
    assert db.get_all_sessions() == []