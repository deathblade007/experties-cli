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
