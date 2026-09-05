import io

import pytest
from rich.console import Console

from experties.theme import EXPERTIES_THEME
from experties.timer import (
    SLEEP_GAP_THRESHOLD,
    TICK_SECONDS,
    TimerState,
    _MultiSlot,
    _process_tick,
    _render,
    _render_multi,
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
    big_gap = TICK_SECONDS + SLEEP_GAP_THRESHOLD + 500
    state, elapsed, msg = _process_tick(TimerState.RUNNING, 10.0, big_gap, None)
    assert state == TimerState.SLEEP_PAUSED
    assert elapsed == 10.0
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


# -- _render_multi (multi-timer watch dialog) -------------------------------

def _rendered(group) -> str:
    console = Console(width=80, file=io.StringIO(), highlight=False, theme=EXPERTIES_THEME)
    console.print(group)
    return console.file.getvalue()


def test_render_multi_shows_every_timers_name():
    slots = [
        _MultiSlot("Python", 30.0, TimerState.RUNNING),
        _MultiSlot("Maths", 15.0, TimerState.PAUSED),
    ]
    output = _rendered(_render_multi(slots, selected=0, message=""))
    assert "Python" in output
    assert "Maths" in output


def test_render_multi_shows_running_and_paused_status_distinctly():
    slots = [
        _MultiSlot("Python", 30.0, TimerState.RUNNING),
        _MultiSlot("Maths", 15.0, TimerState.PAUSED),
    ]
    output = _rendered(_render_multi(slots, selected=0, message=""))
    assert "RUNNING" in output
    assert "PAUSED" in output


def test_render_multi_marks_the_selected_timer():
    slots = [
        _MultiSlot("Python", 30.0, TimerState.RUNNING),
        _MultiSlot("Maths", 15.0, TimerState.RUNNING),
    ]
    output_select_python = _rendered(_render_multi(slots, selected=0, message=""))
    output_select_maths = _rendered(_render_multi(slots, selected=1, message=""))
    assert "\u25b8" in output_select_python
    assert "\u25b8" in output_select_maths
    # The marker moves with the selection rather than always sitting on
    # the same line regardless of which index is passed in.
    assert output_select_python != output_select_maths


def test_render_multi_shows_elapsed_time_formatted():
    slots = [_MultiSlot("Python", 3661.0, TimerState.RUNNING)]  # 1h 1m 1s
    output = _rendered(_render_multi(slots, selected=0, message=""))
    assert format_hms(3661.0) in output


def test_render_multi_shows_keybinding_hints():
    slots = [_MultiSlot("Python", 0.0, TimerState.RUNNING)]
    output = _rendered(_render_multi(slots, selected=0, message=""))
    for hint in ("select", "pause/resume", "stop", "cancel", "exit"):
        assert hint in output


def test_render_multi_shows_a_message_when_present():
    slots = [_MultiSlot("Python", 0.0, TimerState.SLEEP_PAUSED)]
    output = _rendered(_render_multi(slots, selected=0, message="Detected 00:15:00 away"))
    assert "Detected 00:15:00 away" in output


# -- _render (single-timer dialog) -------------------------------------
# Note: this function went untested until now, which is exactly how a
# Panel(..., title_style=...) call -- title_style isn't a valid Panel
# argument, only Table's -- made it all the way to a real crash before
# being caught. These exist specifically to make sure constructing and
# rendering the single-timer Panel can never silently go untested again.

def test_render_returns_a_panel_without_raising():
    # The minimal regression test for the actual bug: Panel(..., title_style=...)
    # raises TypeError at construction time, before any rendering happens.
    _render("Python", 30.0, TimerState.RUNNING, "")


def test_render_shows_skill_name_and_elapsed_time():
    output = _rendered(_render("Python", 3661.0, TimerState.RUNNING, ""))
    assert "Python" in output
    assert format_hms(3661.0) in output


def test_render_shows_running_and_paused_status_distinctly():
    running = _rendered(_render("Python", 0.0, TimerState.RUNNING, ""))
    paused = _rendered(_render("Python", 0.0, TimerState.PAUSED, ""))
    assert "RUNNING" in running
    assert "PAUSED" in paused


def test_render_shows_a_message_when_present():
    output = _rendered(_render("Python", 0.0, TimerState.SLEEP_PAUSED, "Detected 00:15:00 away"))
    assert "Detected 00:15:00 away" in output


def test_render_shows_keybinding_hints():
    output = _rendered(_render("Python", 0.0, TimerState.RUNNING, ""))
    for hint in ("pause", "stop", "cancel"):
        assert hint in output