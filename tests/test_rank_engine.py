import pytest

from experties.rank_engine import RANK_TABLE, crossed_rank_up, division_thresholds, get_rank_status


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


# -- divisions --------------------------------------------------------

def test_ranks_below_bronze_1_have_no_divisions():
    for name in ["Unranked", "Mud 1", "Wood 3", "Stone 2", "Copper 3"]:
        index = next(i for i, r in enumerate(RANK_TABLE) if r.name == name)
        assert division_thresholds(index) is None


def test_top_rank_has_no_divisions():
    top_index = len(RANK_TABLE) - 1
    assert RANK_TABLE[top_index].name == "S"
    assert division_thresholds(top_index) is None


def test_bronze_1_division_thresholds_match_the_sheet():
    index = next(i for i, r in enumerate(RANK_TABLE) if r.name == "Bronze 1")
    thresholds = division_thresholds(index)
    assert thresholds == pytest.approx([73, 75.5, 78, 80.5])


def test_b_rank_division_thresholds_match_the_sheet():
    index = next(i for i, r in enumerate(RANK_TABLE) if r.name == "B")
    thresholds = division_thresholds(index)
    assert thresholds == pytest.approx([5038, 5204.25, 5370.5, 5536.75])


def test_display_name_has_no_division_suffix_below_bronze_1():
    assert get_rank_status(17).display_name == "Mud 1"


def test_display_name_shows_division_1_at_start_of_bronze_1():
    assert get_rank_status(73).display_name == "Bronze 1 Division 1"


def test_display_name_shows_division_3_partway_through_bronze_1():
    # 78h is exactly Bronze 1's division III threshold from the sheet.
    assert get_rank_status(78).display_name == "Bronze 1 Division 3"


def test_display_name_stays_division_3_until_division_4_threshold():
    assert get_rank_status(80.49).display_name == "Bronze 1 Division 3"


def test_display_name_advances_to_division_4():
    assert get_rank_status(80.5).display_name == "Bronze 1 Division 4"


def test_display_name_switches_to_next_rank_division_1_at_full_threshold():
    # 83h is Bronze 2's own threshold — the full rank, not just a division.
    assert get_rank_status(83).display_name == "Bronze 2 Division 1"


def test_display_name_for_top_rank_has_no_division_suffix():
    assert get_rank_status(8274).display_name == "S"
    assert get_rank_status(999_999).display_name == "S"


def test_divisions_do_not_change_hours_to_next_or_progress_fraction():
    # The division system only changes display_name — hours_to_next and
    # progress_fraction must still measure the full rank-to-rank span.
    status = get_rank_status(78)  # Bronze 1 Division 3
    assert status.current.name == "Bronze 1"
    assert status.next.name == "Bronze 2"
    assert status.hours_to_next == pytest.approx(5.0)  # 83 - 78, not division-based
    assert status.progress_fraction == pytest.approx((78 - 73) / (83 - 73))