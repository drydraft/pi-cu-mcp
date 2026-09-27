"""Mouse target validation must reject a window covering an approved one."""

from __future__ import annotations

import subprocess
import time
import ctypes
from pathlib import Path

import pytest

from windows_mcp.backend import PywinautoBackend


def _wait_for_window(backend: PywinautoBackend, name: str):
    for _ in range(40):
        match = next((item for item in backend.list_windows() if name in item.title), None)
        if match:
            return match
        time.sleep(0.1)
    raise AssertionError(f"Window {name} did not appear")


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows desktop only")
def test_mouse_target_rejects_covering_window(tmp_path: Path) -> None:
    first_file = tmp_path / "mcp-first-window.txt"
    second_file = tmp_path / "mcp-covering-window.txt"
    first_file.write_text("first", encoding="utf-8")
    second_file.write_text("second", encoding="utf-8")
    first_process = subprocess.Popen(["notepad.exe", str(first_file)])
    second_process = None
    try:
        backend = PywinautoBackend()
        first = _wait_for_window(backend, first_file.name)
        second_process = subprocess.Popen(["notepad.exe", str(second_file)])
        second = _wait_for_window(backend, second_file.name)
        left, top, right, bottom = first.bounds
        assert ctypes.windll.user32.MoveWindow(second.hwnd, left, top, right-left, bottom-top, True)
        backend._wrapper(second.hwnd).set_focus()
        time.sleep(0.1)

        with pytest.raises(ValueError, match="covered"):
            backend._assert_target_point(first, 100, 100)
    finally:
        first_process.terminate()
        first_process.wait(timeout=5)
        if second_process:
            second_process.terminate()
            second_process.wait(timeout=5)
