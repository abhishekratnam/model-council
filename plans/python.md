# Python project guidance

- Inspect `pyproject.toml`, `uv.lock`, `poetry.lock`, `requirements*.txt`, and the README to identify the environment and documented commands.
- Prefer the project's existing environment and scripts. Check for `uv`, Poetry, or a virtual environment before choosing a package command; do not install dependencies unless the user-approved plan authorizes it.
- Run the documented tests or checks. For a web app, find its documented development server command and bind it to `127.0.0.1` on the fresh `{port}` supplied by the workspace runner; use the supplied loopback `probe_url`.
- Do not assume a framework or entry point from Python files alone. If no local web startup path is documented or discoverable, report that and ask before inventing one.
