# Security policy

This project injects input into the signed-in Windows desktop. Treat it as a high-impact local automation tool.

Report security issues privately to the repository maintainers instead of opening a public issue with exploit details. Include the affected version, Windows version, reproduction steps, and the smallest safe proof you can provide.

The server is intentionally local and stdio-only. It does not provide a network listener. It still cannot bypass Windows session, visibility, or privilege boundaries.
