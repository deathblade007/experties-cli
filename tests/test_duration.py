import pytest

from experties.duration import parse_duration


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1h30m", 1.5),
        ("1h 30m", 1.5),
        ("1.5h", 1.5),
        ("90m", 1.5),
        ("2h", 2.0),
        ("45m", 0.75),
        ("1.5", 1.5),
        ("1H30M", 1.5),
        ("  2h  ", 2.0),
    ],
)
def test_parses_expected_formats(text, expected):
    assert parse_duration(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "   ", "abc", "1x", "h30m", "-1h", "1h-30m"])
def test_rejects_unparseable_input(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_rejects_zero_duration():
    with pytest.raises(ValueError):
        parse_duration("0h")
    with pytest.raises(ValueError):
        parse_duration("0")
