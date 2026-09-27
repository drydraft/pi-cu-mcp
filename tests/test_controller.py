from __future__ import annotations

from contextlib import contextmanager
import pytest

from windows_mcp.core import Allowlist, Controller, Snapshot, WindowInfo


class MemoryDesktop:
    def __init__(self) -> None:
        self.window = WindowInfo(101, "Untitled - Notepad", "notepad.exe", (10, 20, 410, 320))
        self.actions: list[tuple[str, dict]] = []
        self.content = "unchanged"
        self.exclusive_depth = 0

    @contextmanager
    def exclusive(self):
        self.exclusive_depth += 1
        try:
            yield
        finally:
            self.exclusive_depth -= 1

    def list_windows(self) -> list[WindowInfo]:
        return [self.window]

    def get_window(self, hwnd: int) -> WindowInfo:
        if hwnd != self.window.hwnd:
            raise ValueError("window closed")
        return self.window

    def capture(self, hwnd: int) -> Snapshot:
        self.get_window(hwnd)
        assert self.exclusive_depth == 1
        return Snapshot(tree=f"[0] Edit {self.content}", image_png=b"PNG", elements={0: object()})

    def validate_snapshot(self, window: WindowInfo, snapshot: Snapshot) -> Snapshot:
        assert self.exclusive_depth == 1
        if snapshot.tree != f"[0] Edit {self.content}":
            raise ValueError("Window content changed; observe_window again")
        return self.capture(window.hwnd)

    def perform(self, name: str, window: WindowInfo, snapshot: Snapshot, **arguments: object) -> None:
        assert self.exclusive_depth == 1
        self.actions.append((name, arguments))

    def launch_app(self, app: str) -> None:
        self.actions.append(("launch_app", {"app": app}))


def test_allowlist_matches_exact_executable_name() -> None:
    allowed = Allowlist(" Notepad.exe, CALC.EXE ")
    assert allowed.permits("notepad.EXE")
    assert not allowed.permits("notepad.exe.bat")
    assert not Allowlist("").permits("notepad.exe")


def test_explicit_wildcard_allows_every_executable() -> None:
    allowed = Allowlist(" * ")
    assert allowed.permits("notepad.exe")
    assert allowed.permits("powershell.exe")
    assert allowed.permits("custom-app.exe")
    assert not Allowlist("notepad.exe").permits("powershell.exe")


def test_action_consumes_observation_and_requires_a_fresh_one() -> None:
    desktop = MemoryDesktop()
    controller = Controller(desktop, Allowlist("notepad.exe"))
    first = controller.observe_window(101)

    second = controller.act("click", 101, first.token, x=30, y=40)

    assert second.token != first.token
    assert desktop.actions == [("click", {"x": 30, "y": 40})]
    with pytest.raises(ValueError, match="stale"):
        controller.act("click", 101, first.token, x=30, y=40)
    assert len(desktop.actions) == 1


def test_bad_token_does_not_consume_another_agents_current_observation() -> None:
    desktop = MemoryDesktop()
    controller = Controller(desktop, Allowlist("notepad.exe"))
    old = controller.observe_window(101)
    current = controller.observe_window(101)

    with pytest.raises(ValueError, match="stale"):
        controller.act("click", 101, old.token, x=30, y=40)
    controller.act("click", 101, current.token, x=30, y=40)

    assert len(desktop.actions) == 1


def test_action_rejects_window_identity_change_before_input() -> None:
    desktop = MemoryDesktop()
    controller = Controller(desktop, Allowlist("notepad.exe"))
    first = controller.observe_window(101)
    desktop.window = WindowInfo(101, "Other", "calc.exe", (10, 20, 410, 320))

    with pytest.raises(ValueError, match="changed"):
        controller.act("click", 101, first.token, x=30, y=40)
    assert desktop.actions == []


def test_observation_rejects_unapproved_app() -> None:
    desktop = MemoryDesktop()
    controller = Controller(desktop, Allowlist("calc.exe"))
    with pytest.raises(PermissionError, match="notepad.exe"):
        controller.observe_window(101)


def test_launch_requires_exact_approval() -> None:
    desktop = MemoryDesktop()
    controller = Controller(desktop, Allowlist("notepad.exe"))
    controller.launch_app("notepad.exe")
    with pytest.raises(PermissionError):
        controller.launch_app("powershell.exe")
    assert desktop.actions == [("launch_app", {"app": "notepad.exe"})]


def test_list_windows_only_exposes_approved_apps() -> None:
    desktop = MemoryDesktop()
    assert Controller(desktop, Allowlist("")).list_windows() == []
    assert Controller(desktop, Allowlist("notepad.exe")).list_windows() == [desktop.window]
    assert Controller(desktop, Allowlist("*")).list_windows() == [desktop.window]


def test_wildcard_allows_observation_and_launch_of_other_app() -> None:
    desktop = MemoryDesktop()
    desktop.window = WindowInfo(202, "Other App", "other.exe", (10, 20, 410, 320))
    controller = Controller(desktop, Allowlist("*"))
    observed = controller.observe_window(202)
    assert observed.window.exe == "other.exe"
    controller.launch_app("other.exe")
    assert desktop.actions == [("launch_app", {"app": "other.exe"})]


def test_changed_content_rejects_old_observation_before_input() -> None:
    desktop = MemoryDesktop()
    controller = Controller(desktop, Allowlist("notepad.exe"))
    observed = controller.observe_window(101)
    desktop.content = "new button"
    with pytest.raises(ValueError, match="content changed"):
        controller.act("click", 101, observed.token, x=30, y=40)
    assert desktop.actions == []
