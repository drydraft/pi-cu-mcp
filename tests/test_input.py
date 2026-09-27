import pytest

from windows_mcp.input import parse_key_chord, require_point


def test_key_chord_normalizes_supported_modifiers_and_key() -> None:
    assert parse_key_chord("Ctrl+Shift+A") == ("^+a",)
    assert parse_key_chord("Enter") == ("{ENTER}",)


@pytest.mark.parametrize("key", ["Win+R", "Meta+X", "Ctrl+", "Ctrl+Alt+Delete", "Control+Alt+Delete"])
def test_key_chord_rejects_system_or_incomplete_shortcuts(key: str) -> None:
    with pytest.raises(ValueError):
        parse_key_chord(key)


def test_point_must_be_inside_observed_window() -> None:
    assert require_point((10, 20, 410, 320), 20, 30) == (30, 50)
    with pytest.raises(ValueError, match="outside"):
        require_point((10, 20, 410, 320), 401, 30)
