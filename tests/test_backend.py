"""Live desktop checks use a Notepad process created by this test."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from windows_mcp.backend import PywinautoBackend, _type_unicode


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows desktop only")
def test_list_and_capture_own_notepad_window(tmp_path: Path) -> None:
    file = tmp_path / "mcp-window-probe.txt"
    file.write_text("MCP window probe", encoding="utf-8")
    process = subprocess.Popen(["notepad.exe", str(file)])
    backend = PywinautoBackend()
    try:
        deadline = time.monotonic() + 10
        window = None
        while time.monotonic() < deadline:
            window = next((item for item in backend.list_windows() if file.name in item.title), None)
            if window:
                break
            time.sleep(0.2)
        assert window is not None, "Notepad window did not appear"
        assert window.exe.lower() == "notepad.exe"

        snapshot = backend.capture(window.hwnd)

        assert snapshot.image_png.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(snapshot.image_png) > 1000
        assert snapshot.tree

        _type_unicode(" visible change")
        with pytest.raises(ValueError, match="content changed"):
            backend.validate_snapshot(window, snapshot)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
