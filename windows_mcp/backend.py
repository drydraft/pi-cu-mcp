"""Windows UI Automation backend for the local MCP server."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import time

from PIL import Image, ImageChops, ImageGrab
from pywinauto import Desktop, keyboard, mouse

from .core import Snapshot, WindowInfo
from .input import parse_key_chord, require_point


if os.name != "nt":
    raise RuntimeError("Pi CU MCP requires Windows 10 or Windows 11 with an interactive desktop")


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.WindowFromPoint.argtypes = (wintypes.POINT,)
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetAncestor.restype = wintypes.HWND
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
)
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
_kernel32.ReleaseMutex.restype = wintypes.BOOL
_user32.SendInput.argtypes = (wintypes.UINT, ctypes.c_void_p, ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT


class _KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("virtual_key", wintypes.WORD),
        ("scan_code", wintypes.WORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", wintypes.WPARAM),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("keyboard", _KeyboardInput), ("padding", ctypes.c_byte * 32)]


class _Input(ctypes.Structure):
    _fields_ = [("kind", wintypes.DWORD), ("data", _InputUnion)]


def _type_unicode(text: str) -> None:
    for offset in range(0, len(encoded := text.encode("utf-16-le", "surrogatepass")), 2):
        code_unit = int.from_bytes(encoded[offset : offset + 2], "little")
        for flags in (0x0004, 0x0004 | 0x0002):  # UNICODE, then UNICODE | KEYUP
            event = _Input(kind=1, data=_InputUnion(keyboard=_KeyboardInput(0, code_unit, flags, 0, 0)))
            if _user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
                raise OSError(ctypes.get_last_error(), "SendInput failed")


def _process_exe(pid: int) -> str:
    handle = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return "unknown"
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            return "unknown"
        return Path(buffer.value).name
    finally:
        _kernel32.CloseHandle(handle)


class PywinautoBackend:
    def __init__(self) -> None:
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass
        self._desktop = Desktop(backend="uia")

    @contextmanager
    def exclusive(self):
        """Serialize this server's desktop transactions across local MCP processes."""
        handle = _kernel32.CreateMutexW(None, False, "Local\\PiWindowsMcpDesktopInput")
        if not handle:
            raise OSError(ctypes.get_last_error(), "Cannot create desktop input mutex")
        acquired = False
        try:
            result = _kernel32.WaitForSingleObject(handle, 15_000)
            if result not in (0, 0x80):  # WAIT_OBJECT_0 or WAIT_ABANDONED
                raise TimeoutError("Desktop input is busy; retry after the other MCP action finishes")
            acquired = True
            yield
        finally:
            if acquired:
                _kernel32.ReleaseMutex(handle)
            _kernel32.CloseHandle(handle)

    def _wrapper(self, hwnd: int):
        try:
            return self._desktop.window(handle=hwnd).wrapper_object()
        except Exception as exc:
            raise ValueError(f"Window {hwnd} is unavailable") from exc

    def _info(self, wrapper) -> WindowInfo:
        rectangle = wrapper.rectangle()
        return WindowInfo(
            hwnd=int(wrapper.handle),
            title=str(wrapper.window_text() or ""),
            exe=_process_exe(wrapper.process_id()),
            bounds=(rectangle.left, rectangle.top, rectangle.right, rectangle.bottom),
        )

    def list_windows(self) -> list[WindowInfo]:
        windows: list[WindowInfo] = []
        for wrapper in self._desktop.windows():
            try:
                if wrapper.is_visible() and wrapper.window_text().strip():
                    windows.append(self._info(wrapper))
            except Exception:
                continue
        return windows

    def get_window(self, hwnd: int) -> WindowInfo:
        wrapper = self._wrapper(hwnd)
        if not wrapper.is_visible() or wrapper.is_minimized():
            raise ValueError("Target window is not visible on the active desktop")
        return self._info(wrapper)

    def _assert_target_point(self, window: WindowInfo, x: int, y: int) -> tuple[int, int]:
        point = require_point(window.bounds, x, y)
        hit = _user32.WindowFromPoint(wintypes.POINT(*point))
        root = _user32.GetAncestor(hit, 2) if hit else 0  # GA_ROOT
        if int(root or 0) != window.hwnd:
            raise ValueError(
                f"Target point is covered by another window (hit {int(hit or 0)}, "
                f"root {int(root or 0)}, target {window.hwnd}, point {point}); observe_window again"
            )
        return point

    def capture(self, hwnd: int) -> Snapshot:
        wrapper = self._wrapper(hwnd)
        if wrapper.is_minimized() or not wrapper.is_visible():
            raise ValueError("Target window is not visible on the active desktop")
        wrapper.set_focus()
        time.sleep(0.1)
        foreground = int(_user32.GetForegroundWindow())
        if foreground != hwnd:
            raise ValueError(
                f"Target window {hwnd} did not become foreground (actual {foreground}); "
                "select its current modal window"
            )
        window = self._info(wrapper)
        left, top, right, bottom = window.bounds
        if right <= left or bottom <= top:
            raise ValueError("Target window has invalid bounds")
        image = ImageGrab.grab(bbox=window.bounds, all_screens=True)
        output = BytesIO()
        image.save(output, format="PNG")

        lines: list[str] = []
        elements: dict[int, object] = {}
        queue = deque([(wrapper, 0)])
        while queue and len(elements) < 150:
            item, depth = queue.popleft()
            try:
                info = item.element_info
                name = str(info.name or "").replace("\n", " ")[:120]
                kind = str(info.control_type or "Control")
                rect = item.rectangle()
                index = len(elements)
                elements[index] = item
                lines.append(
                    f"[{index}] {'  ' * depth}{kind} name={name!r} "
                    f"rect=({rect.left-left},{rect.top-top},{rect.right-left},{rect.bottom-top})"
                )
                if depth < 5:
                    queue.extend((child, depth + 1) for child in item.children())
            except Exception:
                continue
        if queue:
            lines.append("[tree truncated after 150 elements]")
        return Snapshot(tree="\n".join(lines), image_png=output.getvalue(), elements=elements)

    def validate_snapshot(self, window: WindowInfo, snapshot: Snapshot) -> Snapshot:
        """Reject stale UI structure or material visual changes before using old targets."""
        if int(_user32.GetForegroundWindow()) != window.hwnd:
            raise ValueError("Target is no longer foreground; observe_window again")
        current = self.capture(window.hwnd)
        if current.tree != snapshot.tree:
            raise ValueError("Window content changed (UI tree); observe_window again")
        with Image.open(BytesIO(snapshot.image_png)) as before, Image.open(BytesIO(current.image_png)) as after:
            if before.size != after.size:
                raise ValueError("Window image changed size; observe_window again")
            # Window edges can repaint while the actual controls remain stable.
            margin = min(8, (before.width - 1) // 2, (before.height - 1) // 2)
            content_box = (margin, margin, before.width - margin, before.height - margin)
            difference = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
            changed = difference.crop(content_box).convert("L").point(lambda value: 255 if value > 40 else 0)
            pixels = changed.histogram()[255]
            if pixels > max(40, before.width * before.height // 10_000):
                raise ValueError(f"Window content changed ({pixels} pixels, region {changed.getbbox()}); observe_window again")
        return current

    def perform(self, name: str, window: WindowInfo, snapshot: Snapshot, **arguments: object) -> None:
        if int(_user32.GetForegroundWindow()) != window.hwnd:
            raise ValueError("Target is no longer foreground; observe_window again")
        hwnd = window.hwnd
        if name == "click":
            index = arguments.get("element_index")
            if index is not None:
                element = snapshot.elements.get(int(index))
                if element is None:
                    raise ValueError("Element index is unavailable; observe_window again")
                if not element.is_visible() or not element.is_enabled():
                    raise ValueError("Element is not visible or enabled; observe_window again")
                rect = element.rectangle()
                left, top, right, bottom = window.bounds
                if rect.left < left or rect.top < top or rect.right > right or rect.bottom > bottom:
                    raise ValueError("Element is outside the target window")
                self._assert_target_point(window, (rect.left + rect.right)//2-left, (rect.top + rect.bottom)//2-top)
                element.click_input(button=str(arguments.get("button", "left")), double=bool(arguments.get("double", False)))
            else:
                point = self._assert_target_point(window, int(arguments["x"]), int(arguments["y"]))
                mouse.click(button=str(arguments.get("button", "left")), coords=point)
                if arguments.get("double"):
                    mouse.click(button=str(arguments.get("button", "left")), coords=point)
        elif name == "type_text":
            _type_unicode(str(arguments["text"]))
        elif name == "press_key":
            keyboard.send_keys(parse_key_chord(str(arguments["key"]))[0], pause=0.01)
        elif name == "scroll":
            point = self._assert_target_point(window, int(arguments["x"]), int(arguments["y"]))
            delta = int(arguments["delta_y"])
            if delta == 0:
                raise ValueError("delta_y must be nonzero")
            steps = max(1, round(abs(delta) / 120))
            mouse.scroll(coords=point, wheel_dist=-steps if delta > 0 else steps)
        elif name == "drag":
            from_x, from_y = int(arguments["from_x"]), int(arguments["from_y"])
            to_x, to_y = int(arguments["to_x"]), int(arguments["to_y"])
            for step in range(11):
                self._assert_target_point(
                    window,
                    round(from_x + (to_x-from_x) * step / 10),
                    round(from_y + (to_y-from_y) * step / 10),
                )
            start = require_point(window.bounds, from_x, from_y)
            end = require_point(window.bounds, to_x, to_y)
            mouse.press(coords=start)
            try:
                for step in range(1, 11):
                    mouse.move(coords=(round(start[0] + (end[0]-start[0]) * step / 10), round(start[1] + (end[1]-start[1]) * step / 10)))
                    time.sleep(0.01)
            finally:
                mouse.release(coords=end)
        elif name == "set_value":
            element = snapshot.elements.get(int(arguments["element_index"]))
            if element is None:
                raise ValueError("Element index is unavailable; observe_window again")
            if not element.is_visible() or not element.is_enabled():
                raise ValueError("Element is not visible or enabled; observe_window again")
            rect = element.rectangle()
            left, top, right, bottom = window.bounds
            if rect.left < left or rect.top < top or rect.right > right or rect.bottom > bottom:
                raise ValueError("Element is outside the target window")
            self._assert_target_point(window, (rect.left + rect.right)//2-left, (rect.top + rect.bottom)//2-top)
            if not hasattr(element, "set_edit_text"):
                raise ValueError("Selected element does not support setting text")
            element.set_edit_text(str(arguments["value"]))
        else:
            raise ValueError(f"Unsupported action: {name}")
        if self.get_window(hwnd).exe.casefold() != window.exe.casefold():
            raise ValueError("Target window identity changed after input")

    def launch_app(self, app: str) -> None:
        path = shutil.which(app)
        if not path:
            raise FileNotFoundError(f"Executable {app} was not found on PATH")
        subprocess.Popen([path], shell=False)
