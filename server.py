"""Compatibility entrypoint. Keep stdout reserved for MCP messages."""

from windows_mcp.__main__ import main


if __name__ == "__main__":
    main()
