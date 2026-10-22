# Repository instructions

- Use the existing `venv/`; never delete or recreate it.
- Run Python commands through `venv/bin/python3`. Do not use bare `python` or `pip`.
- Install packages with `venv/bin/python3 -m pip install -r requirements.txt`.
- Shell command allowlist: `bun`, `cargo`, `deno`, `go`, `node`, `npm`, `npx`, `php`, `pip`, `pnpm`, `pytest`, `python`, `python3`, `ruby`, `ruff`, `uv`, and `yarn`.
- Run tests with `venv/bin/python3 -m pytest` (normally `venv/bin/python3 -m pytest -q`).
- Keep shell work inside the repository. Never delete or recreate `venv/`.
- Ignore the directories and binary suffixes listed below when inspecting project source.

## Plan mode and approvals

- The coding agent must present one structured plan with ordered steps, exact relative file paths, exact commands, and a risk level before implementation.
- One approval authorizes the listed in-scope files and exact commands for that run. Keep showing diffs and recording applied changes.
- A rejected plan may be revised and presented once. A second rejection ends the run without implementation.
- If plan review is unanswered for `MC_CONFIRM_TIMEOUT_S` seconds (default 1800), save the plan to `.model_council/session_state.json`, mark the run paused, and offer approve, reject, or discard on the next app start. Approval resumes the saved plan.
- Ask again for actions outside the approved scope. Network, destructive, and outside-workspace actions always need explicit approval; blocked destructive commands remain blocked by command validation.
- The Workspace **Full access** toggle skips per-command approval for ordinary allowlisted commands. Network and outside-workspace commands still ask; file changes still follow the approved-plan scope.
- On macOS, show an `osascript` notification when a plan or an out-of-scope action awaits approval.
- Do not put API keys or provider secrets in persisted session state.

```python
IGNORED_DIR_NAMES = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".idea",
    ".vscode", ".zcode", ".eggs", "site-packages", ".tox", ".next", ".cache",
}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".bz2", ".xz", ".7z", ".rar", ".jar", ".whl", ".so", ".dylib",
    ".dll", ".exe", ".bin", ".o", ".a", ".class", ".woff", ".woff2", ".ttf",
    ".otf", ".eot", ".mp3", ".mp4", ".mov", ".avi", ".db", ".sqlite",
    ".sqlite3", ".pyc", ".pyo", ".DS_Store",
}

ALLOWED_COMMAND_EXECUTABLES = {
    "python", "python3", "pytest", "ruff", "pip", "uv",
    "node", "npm", "npx", "pnpm", "yarn", "bun", "deno",
    "go", "cargo", "ruby", "php",
}
FORBIDDEN_COMMAND_TOKENS = {"sudo", "rm", "shutdown", "reboot", "kill", "mkfs", "dd"}
```
