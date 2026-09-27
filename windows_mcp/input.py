"""Validation and key syntax conversion for scoped Windows input."""

from __future__ import annotations


_SPECIAL = {
    "enter": "ENTER", "return": "ENTER", "tab": "TAB", "escape": "ESC",
    "esc": "ESC", "backspace": "BACKSPACE", "delete": "DELETE",
    "insert": "INSERT", "up": "UP", "down": "DOWN", "left": "LEFT",
    "right": "RIGHT", "home": "HOME", "end": "END", "pageup": "PGUP",
    "pagedown": "PGDN", "space": "SPACE",
}


def parse_key_chord(chord: str) -> tuple[str]:
    parts = [part.strip().casefold() for part in chord.split("+")]
    if not parts or any(not part for part in parts):
        raise ValueError("Incomplete key chord")
    if any(part in {"win", "windows", "meta", "super", "cmd", "command", "os"} for part in parts):
        raise ValueError("Windows-key shortcuts are unavailable")
    modifiers = ["ctrl" if part == "control" else part for part in parts[:-1]]
    if len(set(modifiers)) != len(modifiers) or any(part not in {"ctrl", "alt", "shift"} for part in modifiers):
        raise ValueError("Unsupported key chord")
    key = parts[-1]
    if set(modifiers) >= {"ctrl", "alt"} and key == "delete":
        raise ValueError("Ctrl+Alt+Delete is unavailable")
    if len(key) == 1 and key.isalnum():
        encoded = key
    elif key in _SPECIAL:
        encoded = "{" + _SPECIAL[key] + "}"
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        encoded = "{" + key.upper() + "}"
    else:
        raise ValueError("Unsupported key")
    prefix = "".join(symbol for name, symbol in (("ctrl", "^"), ("alt", "%"), ("shift", "+")) if name in modifiers)
    return (prefix + encoded,)


def require_point(bounds: tuple[int, int, int, int], x: int, y: int) -> tuple[int, int]:
    left, top, right, bottom = bounds
    if not 0 <= x < right - left or not 0 <= y < bottom - top:
        raise ValueError("Point is outside the observed window")
    return left + x, top + y
