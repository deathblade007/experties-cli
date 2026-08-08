import pytest

from experties.timer import (
    SLEEP_GAP_THRESHOLD,
    TICK_SECONDS,
    TimerState,
    _process_tick,
    format_hms,
)


def test_format_hms_zero():
    assert format_hms(0) == "00:00:00"


def test_format_hms_minutes_and_seconds():
    assert format_hms(61) == "00:01:01"


def test_format_hms_hours():
    assert format_hms(3661) == "01:01:01"


def test_format_hms_negative_clamped_to_zero():
    assert format_hms(-5) == "00:00:00"


def test_running_normal_gap_accumulates_elapsed():
    state, elapsed, msg = _process_tick(TimerState.RUNNING, 10.0, TICK_SECONDS, None)
    assert state == TimerState.RUNNING
    assert elapsed == pytest.approx(11.0)
    assert msg == ""


def test_paused_normal_gap_does_not_accumulate():
    state, elapsed, msg = _process_tick(TimerState.PAUSED, 10.0, TICK_SECONDS, None)
    assert state == TimerState.PAUSED
    assert elapsed == 10.0


def test_sleep_paused_normal_gap_does_not_accumulate():
    state, elapsed, msg = _process_tick(TimerState.SLEEP_PAUSED, 10.0, TICK_SECONDS, None)
    assert state == TimerState.SLEEP_PAUSED
    assert elapsed == 10.0


def test_large_gap_while_running_triggers_sleep_pause_without_counting_gap():
    big_gap = TICK_SECONDS + SLEEP_GAP_THRESHOLD + 500  # well past the threshold
    state, elapsed, msg = _process_tick(TimerState.RUNNING, 10.0, big_gap, None)
    assert state == TimerState.SLEEP_PAUSED
    assert elapsed == 10.0  # the gap itself is never added to elapsed
    assert "away" in msg


def test_gap_just_under_threshold_does_not_trigger_sleep_pause():
    small_gap = TICK_SECONDS + SLEEP_GAP_THRESHOLD - 1
    state, elapsed, msg = _process_tick(TimerState.RUNNING, 10.0, small_gap, None)
    assert state == TimerState.RUNNING
    assert elapsed == pytest.approx(10.0 + small_gap)
    assert msg == ""


def test_space_pauses_running_and_still_counts_the_gap_before_the_pause():
    state, elapsed, msg = _process_tick(TimerState.RUNNING, 5.0, 0.2, " ")
    assert state == TimerState.PAUSED
    assert elapsed == pytest.approx(5.2)


def test_space_resumes_paused_without_adding_the_gap():
    state, elapsed, msg = _process_tick(TimerState.PAUSED, 5.0, 0.01, " ")
    assert state == TimerState.RUNNING
    assert elapsed == 5.0


def test_space_resumes_sleep_paused_and_clears_message():
    state, elapsed, msg = _process_tick(
        TimerState.SLEEP_PAUSED, 5.0, 0.01, " ", message="Detected 1:00:00 away"
    )
    assert state == TimerState.RUNNING
    assert msg == ""


def test_unrelated_key_still_accumulates_running_time():
    state, elapsed, msg = _process_tick(TimerState.RUNNING, 5.0, 0.3, "x")
    assert state == TimerState.RUNNING
    assert elapsed == pytest.approx(5.3)


def test_message_persists_while_sleep_paused_with_no_key():
    state, elapsed, msg = _process_tick(
        TimerState.SLEEP_PAUSED, 10.0, TICK_SECONDS, None, message="Detected 1:00:00 away"
    )
    assert state == TimerState.SLEEP_PAUSED
    assert msg == "Detected 1:00:00 away"


def test_sleep_detected_overwrites_any_previous_message():
    big_gap = TICK_SECONDS + SLEEP_GAP_THRESHOLD + 50
    state, elapsed, msg = _process_tick(
        TimerState.RUNNING, 10.0, big_gap, None, message="stale message"
    )
    assert "away" in msg
    assert msg != "stale message"
