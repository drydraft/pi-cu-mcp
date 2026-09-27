"""App permissions and one-use observation state for desktop actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import nullcontext
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4
import re


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    exe: str
    bounds: tuple[int, int, int, int]


@dataclass
class Snapshot:
    tree: str
    image_png: bytes
    elements: dict[int, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    token: str
    window: WindowInfo
    snapshot: Snapshot


class DesktopBackend(Protocol):
    def list_windows(self) -> list[WindowInfo]: ...
    def get_window(self, hwnd: int) -> WindowInfo: ...
    def capture(self, hwnd: int) -> Snapshot: ...
    def perform(self, name: str, window: WindowInfo, snapshot: Snapshot, **arguments: object) -> None: ...
    def launch_app(self, app: str) -> None: ...


class Allowlist:
    def __init__(self, csv_names: str) -> None:
        self._names = {name.strip().casefold() for name in csv_names.split(",") if name.strip()}

    def permits(self, executable: str) -> bool:
        return "*" in self._names or executable.casefold() in self._names

    def require(self, executable: str) -> None:
        if not self.permits(executable):
            raise PermissionError(
                f"{executable} is not approved. Add its executable name or '*' to "
                "WINDOWS_MCP_ALLOWED_APPS and restart the MCP server."
            )


class Controller:
    def __init__(self, backend: DesktopBackend, allowlist: Allowlist) -> None:
        self._backend = backend
        self._allowlist = allowlist
        self._current: dict[int, Observation] = {}
        self._lock = RLock()

    def list_windows(self) -> list[WindowInfo]:
        with self._lock:
            return [window for window in self._backend.list_windows() if self._allowlist.permits(window.exe)]

    def _exclusive(self):
        exclusive = getattr(self._backend, "exclusive", None)
        return exclusive() if exclusive is not None else nullcontext()

    def _observe_unlocked(self, hwnd: int) -> Observation:
        window = self._backend.get_window(hwnd)
        self._allowlist.require(window.exe)
        snapshot = self._backend.capture(hwnd)
        observation = Observation(uuid4().hex, window, snapshot)
        self._current[hwnd] = observation
        return observation

    def observe_window(self, hwnd: int) -> Observation:
        with self._lock, self._exclusive():
            return self._observe_unlocked(hwnd)

    def act(self, name: str, hwnd: int, token: str, **arguments: object) -> Observation:
        with self._lock, self._exclusive():
            old = self._current.get(hwnd)
            if old is None or old.token != token:
                raise ValueError("Observation token is stale; call observe_window again.")
            del self._current[hwnd]
            current = self._backend.get_window(hwnd)
            if (current.exe.casefold(), current.title, current.bounds) != (old.window.exe.casefold(), old.window.title, old.window.bounds):
                raise ValueError("Target window changed; call observe_window again.")
            self._allowlist.require(current.exe)
            validate_snapshot = getattr(self._backend, "validate_snapshot", None)
            target_snapshot = old.snapshot
            if validate_snapshot is not None:
                target_snapshot = validate_snapshot(current, old.snapshot)
            self._backend.perform(name, current, target_snapshot, **arguments)
            return self._observe_unlocked(hwnd)

    def launch_app(self, app: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.exe", app):
            raise ValueError("app must be an executable name such as notepad.exe, without a path or arguments")
        with self._lock, self._exclusive():
            self._allowlist.require(app)
            self._backend.launch_app(app)
