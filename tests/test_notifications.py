import subprocess
from unittest.mock import MagicMock, patch

from experties.notifications import (
    _escape_for_applescript,
    notify_all_level_ups,
    notify_level_up,
)
from experties.rank_engine import Rank


def test_escape_handles_quotes():
    assert _escape_for_applescript('say "hi"') == 'say \\"hi\\"'


def test_escape_handles_backslashes():
    assert _escape_for_applescript("a\\b") == "a\\\\b"


def test_escape_handles_both_together():
    assert _escape_for_applescript('back\\slash and "quote"') == 'back\\\\slash and \\"quote\\"'


def test_notify_returns_false_when_osascript_missing():
    with patch("experties.notifications.shutil.which", return_value=None):
        assert notify_level_up("Coding", Rank("Mud 1", 16)) is False


def test_notify_calls_osascript_and_returns_true_on_success():
    with patch("experties.notifications.shutil.which", return_value="/usr/bin/osascript"), patch(
        "experties.notifications.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert notify_level_up("Coding", Rank("Mud 1", 16)) is True
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        assert called_args[0] == "osascript"


def test_notify_script_contains_skill_and_rank_name():
    with patch("experties.notifications.shutil.which", return_value="/usr/bin/osascript"), patch(
        "experties.notifications.subprocess.run"
    ) as mock_run:
        notify_level_up("Coding", Rank("Mud 1", 16))
        script = mock_run.call_args[0][0][2]  # ["osascript", "-e", script]
        assert "Coding" in script
        assert "Mud 1" in script


def test_notify_escapes_quotes_in_names_so_the_script_cant_break():
    with patch("experties.notifications.shutil.which", return_value="/usr/bin/osascript"), patch(
        "experties.notifications.subprocess.run"
    ) as mock_run:
        notify_level_up('Say "Hi"', Rank("Mud 1", 16))
        script = mock_run.call_args[0][0][2]
        assert '\\"Hi\\"' in script


def test_notify_returns_false_when_subprocess_raises_called_process_error():
    with patch("experties.notifications.shutil.which", return_value="/usr/bin/osascript"), patch(
        "experties.notifications.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "osascript"),
    ):
        assert notify_level_up("Coding", Rank("Mud 1", 16)) is False


def test_notify_returns_false_on_timeout():
    with patch("experties.notifications.shutil.which", return_value="/usr/bin/osascript"), patch(
        "experties.notifications.subprocess.run",
        side_effect=subprocess.TimeoutExpired("osascript", 5),
    ):
        assert notify_level_up("Coding", Rank("Mud 1", 16)) is False


def test_notify_all_level_ups_fires_one_per_rank_crossed():
    with patch("experties.notifications.shutil.which", return_value="/usr/bin/osascript"), patch(
        "experties.notifications.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        ranks = [Rank("Mud 1", 16), Rank("Mud 2", 19), Rank("Mud 3", 21)]
        notify_all_level_ups("Coding", ranks)
        assert mock_run.call_count == 3


def test_notify_all_level_ups_does_not_raise_when_osascript_unavailable():
    with patch("experties.notifications.shutil.which", return_value=None):
        notify_all_level_ups("Coding", [Rank("Mud 1", 16), Rank("Mud 2", 19)])  # should not raise