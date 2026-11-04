# Python project guidance

**Precedence:** `AGENTS.md` defines shared project discovery, baseline checks,
plan mode, and approvals (sections 1.1, 1.2, and 4). This file adds Python-specific
guidance. `AGENTS.md` takes precedence if instructions conflict, unless this
file is stricter. The workspace runner supplies `{port}` and `probe_url`; use
those values as given.

## 1. Identify the environment

Before running commands, inspect the project manifests and README. Use the
first applicable row below:

| Project files | Environment | Command runner |
|---|---|---|
| `uv.lock`, or `[tool.uv]` in `pyproject.toml` | uv | `uv run …` |
| `poetry.lock`, or `[tool.poetry]` in `pyproject.toml` | Poetry | `poetry run …` |
| Existing `venv/` or `.venv/` | Virtual environment | Its `bin/python3` |
| `requirements*.txt`, with no environment above | pip and virtualenv | `venv/bin/python3 -m …` |
| None of the above | Undetermined | Stop; propose an environment in the plan and ask |

- For `pyproject.toml` without a lockfile, inspect its `[tool.*]` sections and
  the README to identify the intended manager (uv, Poetry, pip, Hatch, or PDM).
  If it remains unclear, ask instead of guessing.
- Follow a manager explicitly pinned by the manifest, even if the table points
  elsewhere. Do not mix package managers.
- Never infer the framework or entry point from `.py` files alone (§1.2).
- Use an existing environment as found. Never delete, recreate, or refresh a
  virtual environment or lockfile.

## 2. Commands

Use the runner selected in §1 for Python commands and checks.

| Goal | uv | Poetry | pip and virtualenv |
|---|---|---|---|
| Create or sync environment *(plan approval required)* | `uv sync` | `poetry install` | `python3 -m venv venv`, then install requirements |
| Install dependencies *(plan approval required)* | `uv sync` | `poetry install` | `venv/bin/python3 -m pip install -r requirements.txt` |
| Add a dependency *(plan approval required; include changes in the diff)* | `uv add <pkg>` | `poetry add <pkg>` | Install with the environment's pip, then pin in `requirements*.txt` |
| Run Python | `uv run python …` | `poetry run python …` | `venv/bin/python3 …` |
| Run tests | `uv run python -m pytest -q` | `poetry run python -m pytest -q` | `venv/bin/python3 -m pytest -q` |
| Lint or format *(only if already configured)* | `uv run ruff check .` | `poetry run ruff check .` | `venv/bin/ruff check .` |

- Do not call bare `python`, `pip`, or `pytest`; use the selected environment's
  runner so commands use the project's interpreter and installed packages.
- The system `python3` is allowed only to create a virtual environment when the
  approved plan authorizes it.

## 3. Dependencies

- Do not install dependencies, create an environment, or access the network
  unless the approved plan explicitly authorizes it (sections 1.2 and 4).
- If no environment exists, propose one in the plan before running commands:
  `uv sync`, `poetry install`, or `python3 -m venv venv` followed by installing
  `requirements.txt`.
- Resolve versions from manifests and lockfiles. Do not hand-edit lockfiles or
  version pins unless that is the task.
- List every dependency change in the plan's file list and include it in the
  diff.

## 4. Tests and checks

- Start with the project's documented checks in the README, `Makefile`,
  `pyproject.toml`, `tox.ini`, `noxfile.py`, or CI configuration.
- If none are documented, use the environment's `python -m pytest -q` command
  from §2.
- Run relevant checks before and after implementation. Report baseline failures
  before proposing unrelated fixes (§1.2).
- Use lint or type-checking tools only when the project already configures them.
  Do not add tooling without plan approval.

## 5. Web applications

- Find the documented development-server command in project documentation,
  scripts, or configuration. Do not infer a command from the framework or
  Python files alone.
- Bind the server to `127.0.0.1` on the fresh `{port}` supplied by the workspace
  runner. Verify the supplied `probe_url` before reporting success.
- Start a fresh server for each run; do not rely on an existing process (§1.2).
- If no local startup path is documented or discoverable, report that and ask
  before inventing commands or configuration.
