# Contributing

Issues and pull requests are welcome.

Before opening a pull request:

1. Run `python -m pytest -q tests/test_controller.py tests/test_input.py`.
2. Run `python -m compileall -q windows_mcp server.py`.
3. For changes to desktop input, test in an unlocked interactive Windows session and describe the application used.

Do not include `.venv`, screenshots containing private data, Pi configuration files from your home directory, or credentials in a pull request.
