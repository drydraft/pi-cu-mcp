"""Exercise the server through the actual MCP stdio protocol."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import ImageContent, TextContent


PROJECT = Path(__file__).resolve().parents[1]


def test_stdio_client_discovers_desktop_tools() -> None:
    async def check() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(PROJECT / "server.py")],
            cwd=PROJECT,
            env={**os.environ, "WINDOWS_MCP_ALLOWED_APPS": "notepad.exe"},
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"list_windows", "observe_window", "click", "type_text", "press_key", "scroll", "drag", "set_value", "launch_app"} <= names
                denied = await session.call_tool("launch_app", {"app": "powershell.exe"})
                assert denied.isError

    asyncio.run(check())


def test_mcp_observe_and_input_round_trip(tmp_path: Path) -> None:
    file = tmp_path / "mcp-round-trip.txt"
    file.write_text("MCP probe", encoding="utf-8")
    process = subprocess.Popen(["notepad.exe", str(file)])

    async def check() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(PROJECT / "server.py")],
            cwd=PROJECT,
            env={**os.environ, "WINDOWS_MCP_ALLOWED_APPS": "notepad.exe"},
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                hwnd = None
                for _ in range(30):
                    result = await session.call_tool("list_windows")
                    windows = json.loads(result.content[0].text)
                    match = next((w for w in windows if file.name in w["title"]), None)
                    if match:
                        hwnd = match["hwnd"]
                        break
                    await asyncio.sleep(0.2)
                assert hwnd is not None

                observed = await session.call_tool("observe_window", {"hwnd": hwnd})
                assert not observed.isError
                assert any(isinstance(block, ImageContent) for block in observed.content)
                details = json.loads(next(block.text for block in observed.content if isinstance(block, TextContent)))
                assert details["window"]["exe"].lower() == "notepad.exe"
                assert "Edit" in details["tree"]
                edit_line = next(line for line in details["tree"].splitlines() if " Edit " in line)
                edit_index = int(edit_line.split("]", 1)[0][1:])

                clicked = await session.call_tool("click", {"hwnd": hwnd, "observation_token": details["observation_token"], "element_index": edit_index})
                assert not clicked.isError
                clicked_details = json.loads(next(block.text for block in clicked.content if isinstance(block, TextContent)))
                typed = await session.call_tool("type_text", {"hwnd": hwnd, "observation_token": clicked_details["observation_token"], "text": " + entered via MCP"})
                assert not typed.isError
                typed_details = json.loads(next(block.text for block in typed.content if isinstance(block, TextContent)))
                assert typed_details["observation_token"] != clicked_details["observation_token"]
                assert any(isinstance(block, ImageContent) for block in typed.content)
                saved = await session.call_tool("press_key", {"hwnd": hwnd, "observation_token": typed_details["observation_token"], "key": "Ctrl+S"})
                assert not saved.isError
                for _ in range(20):
                    if "entered via MCP" in file.read_text(encoding="utf-8"):
                        break
                    await asyncio.sleep(0.1)
                assert "entered via MCP" in file.read_text(encoding="utf-8")

    try:
        asyncio.run(check())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
