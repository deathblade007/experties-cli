import pytest

from experties.rank_engine import RANK_TABLE, crossed_rank_up, get_rank_status


def test_zero_hours_is_unranked():
    assert get_rank_status(0).current.name == "Unranked"


def test_exact_threshold_counts_as_that_rank():
    # 16h exactly is already Mud 1, not still Unranked.
    assert get_rank_status(16).current.name == "Mud 1"


def test_just_below_threshold_is_previous_rank():
    assert get_rank_status(15.99).current.name == "Unranked"


def test_progress_fraction_at_start_of_tier_is_zero():
    assert get_rank_status(16).progress_fraction == 0.0


def test_progress_fraction_partway_through_tier():
    status = get_rank_status(18.9)  # Mud 1 spans 16h -> 19h
    assert status.current.name == "Mud 1"
    assert status.next.name == "Mud 2"
    assert 0 < status.progress_fraction < 1
    assert status.hours_to_next == pytest.approx(0.1)


def test_top_rank_has_no_next():
    status = get_rank_status(8274)
    assert status.current.name == "S"
    assert status.next is None
    assert status.hours_to_next is None
    assert status.progress_fraction is None


def test_hours_far_above_top_rank_still_resolves_to_top():
    assert get_rank_status(999_999).current.name == "S"


def test_table_is_strictly_increasing_with_no_duplicates():
    hours = [r.threshold_hours for r in RANK_TABLE]
    assert hours == sorted(hours)
    assert len(hours) == len(set(hours))


def test_negative_hours_raises():
    with pytest.raises(ValueError):
        get_rank_status(-1)


def test_crossed_rank_up_single_tier():
    assert [r.name for r in crossed_rank_up(10, 17)] == ["Mud 1"]


def test_crossed_rank_up_multiple_tiers_in_one_session():
    # A single long session can jump straight through several tiers.
    assert [r.name for r in crossed_rank_up(10, 25)] == [
        "Mud 1", "Mud 2", "Mud 3", "Wood 1",
    ]


def test_crossed_rank_up_landing_exactly_on_threshold_counts():
    assert [r.name for r in crossed_rank_up(10, 16)] == ["Mud 1"]


def test_crossed_rank_up_no_crossing():
    assert crossed_rank_up(20, 20.5) == []


def test_crossed_rank_up_backwards_is_empty():
    assert crossed_rank_up(50, 40) == []
