"""Sandboxed file access for the code agent.

Every path a user (or model) supplies is resolved inside the workspace root;
dotfiles, symlink escapes, and oversized or binary files are rejected. Nothing
here trusts the caller: the root is fixed by settings, and writes are only
performed after the UI confirms a staged diff.
"""
import difflib
import os
import re
import shlex
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

from model_council_companion.runtime import (
    settings,
    WORKSPACE_MAX_TREE_ENTRIES,
    WORKSPACE_MAX_TREE_DEPTH,
    WORKSPACE_MAX_FILE_BYTES,
    WORKSPACE_MAX_READ_LINES,
    WORKSPACE_SEARCH_MAX_RESULTS,
    WORKSPACE_COMMAND_TIMEOUT_SECONDS,
    WORKSPACE_COMMAND_OUTPUT_CHARS,
    WORKSPACE_SERVER_START_TIMEOUT_SECONDS,
    CODE_AGENT_SESSION_LOG_PATH,
    CODE_AGENT_SESSION_LOG_MAX_CHARS,
)

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


# ── Root & path jail ─────────────────────────────────────────────────────────

_REPO_DIR = Path(__file__).resolve().parents[2]


def workspace_roots() -> list[dict[str, Any]]:
    """Parse the configured root allowlist. `MODEL_COUNCIL_WORKSPACE_ROOT`
    accepts comma-separated paths; when empty the repo's `workspace/` folder
    is the single (auto-created) default. A browser cannot browse the disk,
    so the UI can only switch between these server-configured roots."""
    raw = settings.MODEL_COUNCIL_WORKSPACE_ROOT.strip()
    if not raw:
        default = (_REPO_DIR / "workspace").resolve()
        default.mkdir(parents=True, exist_ok=True)
        if not default.is_dir():
            raise CouncilError(f"Default workspace folder is not available: {default}")
        return [{"path": str(default), "exists": True}]
    seen: list[str] = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = _REPO_DIR / path
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.append(resolved)
    if not seen:
        raise CouncilError("MODEL_COUNCIL_WORKSPACE_ROOT is set but contains no usable paths.")
    return [{"path": path, "exists": Path(path).is_dir()} for path in seen]


def resolve_root(root: str | Path | None) -> Path:
    """Map a UI/model-supplied root selector to an allowed, existing folder."""
    if isinstance(root, Path):
        selected = root.expanduser().resolve()
        if not selected.is_dir():
            raise CouncilError(f"Workspace root does not exist or is not a folder: {selected}")
        return selected
    roots = workspace_roots()
    if root is None or not str(root).strip():
        chosen = roots[0]
    else:
        wanted = str(Path(str(root).strip()).expanduser().resolve())
        chosen = next((entry for entry in roots if entry["path"] == wanted), None)
        if chosen is None:
            raise CouncilError(
                "Workspace root is not in the configured allowlist "
                "(MODEL_COUNCIL_WORKSPACE_ROOT)."
            )
    path = Path(chosen["path"])
    if not path.is_dir():
        raise CouncilError(f"Workspace root does not exist or is not a folder: {path}")
    return path


def workspace_root() -> Path:
    """The default (first) workspace root."""
    return resolve_root(None)


def read_agent_session_log(root: str | None = None) -> str:
    """Return the bounded, application-managed handoff from the prior agent run."""
    root_path = resolve_root(root)
    path = root_path / CODE_AGENT_SESSION_LOG_PATH
    if any(part.is_symlink() for part in (
        root_path / ".model_council",
        root_path / ".model_council/plans",
        path,
    )):
        return ""
    if not path.is_file() or not _is_text_file(path):
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(CODE_AGENT_SESSION_LOG_MAX_CHARS)
    except OSError:
        return ""


def write_agent_session_log(content: str, root: str | None = None) -> dict[str, Any]:
    """Replace the handoff file with a bounded record of the completed agent run."""
    if not isinstance(content, str):
        raise CouncilError("Agent session log must be text.")
    root_path = resolve_root(root)
    state_dir = root_path / ".model_council"
    plans_dir = state_dir / "plans"
    path = root_path / CODE_AGENT_SESSION_LOG_PATH
    if any(part.is_symlink() for part in (state_dir, plans_dir, path)):
        raise CouncilError(f"Agent session log path contains a symlink: {CODE_AGENT_SESSION_LOG_PATH}")
    if (state_dir.exists() and not state_dir.is_dir()) or (plans_dir.exists() and not plans_dir.is_dir()):
        raise CouncilError(f"Agent session log directory is unavailable: {CODE_AGENT_SESSION_LOG_PATH}")
    if path.exists() and not path.is_file():
        raise CouncilError(f"Agent session log target is not a file: {CODE_AGENT_SESSION_LOG_PATH}")
    bounded = content[:CODE_AGENT_SESSION_LOG_MAX_CHARS]
    try:
        plans_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(bounded, encoding="utf-8")
    except OSError as error:
        raise CouncilError(f"Could not write the agent session log: {error}") from error
    return {"path": CODE_AGENT_SESSION_LOG_PATH, "written": True}


def resolve_in_workspace(relative_path: str, root: Path) -> Path:
    """Map a model/user-supplied relative path to a safe absolute path."""
    if not isinstance(relative_path, str):
        raise CouncilError("Path must be text.")
    cleaned = relative_path.strip().replace("\\", "/").strip("/")
    if not cleaned or cleaned == ".":
        return root
    pure = PurePosixPath(cleaned)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        raise CouncilError("Path must be relative to the workspace root and cannot contain '..'.")
    if any(part.startswith(".") for part in pure.parts):
        raise CouncilError("Dotfiles and dot-directories are not accessible.")
    candidate = (root / pure).resolve()
    if candidate != root and root not in candidate.parents:
        raise CouncilError("Path escapes the workspace root.")
    return candidate


def _is_ignored_dir(name: str) -> bool:
    return name in IGNORED_DIR_NAMES or (name.startswith(".") and name not in {".github"})


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES or path.name in BINARY_SUFFIXES:
        return False
    try:
        with path.open("rb") as handle:
            return b"\x00" not in handle.read(8_192)
    except OSError:
        return False


# ── Read-only operations ─────────────────────────────────────────────────────

def list_tree(relative_path: str = "", root: str | None = None) -> dict[str, Any]:
    """Depth-limited listing of files and folders, dirs first, entries capped."""
    base = resolve_in_workspace(relative_path, resolve_root(root))
    if not base.is_dir():
        raise CouncilError(f"Not a folder: {relative_path or '.'}")
    root_path = resolve_root(root)
    entries: list[dict[str, Any]] = []
    truncated = False
    base_depth = len(base.parts)
    stack = [(base, 0)]
    while stack and len(entries) < WORKSPACE_MAX_TREE_ENTRIES:
        current, depth = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            continue
        for child in children:
            if len(entries) >= WORKSPACE_MAX_TREE_ENTRIES:
                truncated = True
                break
            if child.name.startswith(".") and child.name != ".github":
                continue
            if _is_ignored_dir(child.name):
                continue
            rel = child.relative_to(root_path).as_posix()
            if child.is_dir():
                if child.is_symlink():
                    continue
                entries.append({"path": rel, "type": "dir"})
                if depth + 1 < WORKSPACE_MAX_TREE_DEPTH and len(child.parts) - base_depth < WORKSPACE_MAX_TREE_DEPTH:
                    stack.append((child, depth + 1))
            elif child.is_file():
                try:
                    size = child.stat().st_size
                except OSError:
                    size = 0
                entries.append({"path": rel, "type": "file", "size": size})
    if not truncated and stack:
        truncated = True
    return {
        "root": str(root_path),
        "base": relative_path or ".",
        "entries": entries,
        "truncated": truncated,
    }


def read_file(relative_path: str, offset: int = 1, limit: int | None = None, root: str | None = None) -> dict[str, Any]:
    """Read a bounded slice of a text file. Line numbers are 1-based."""
    root_path = resolve_root(root)
    path = resolve_in_workspace(relative_path, root_path)
    if not path.is_file():
        raise CouncilError(f"File not found: {relative_path}")
    size = path.stat().st_size
    if size > WORKSPACE_MAX_FILE_BYTES:
        raise CouncilError(
            f"File is {size:,} bytes; only files up to {WORKSPACE_MAX_FILE_BYTES:,} bytes can be read."
        )
    if not _is_text_file(path):
        raise CouncilError(f"Refusing to read a binary file: {relative_path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise CouncilError(f"File is not valid UTF-8 text: {relative_path}") from error

    offset = max(1, int(offset or 1))
    limit = WORKSPACE_MAX_READ_LINES if limit is None else max(1, min(int(limit), WORKSPACE_MAX_READ_LINES))
    lines = text.splitlines()
    start = min(offset, max(1, len(lines)))
    end = min(len(lines), start - 1 + limit)
    content = "\n".join(lines[start - 1:end])
    truncated = end < len(lines) or offset > 1 or len(text) > WORKSPACE_MAX_FILE_BYTES
    return {
        "path": path.relative_to(root_path).as_posix(),
        "content": content,
        "start_line": start,
        "end_line": end,
        "total_lines": len(lines),
        "size": size,
        "truncated": truncated,
    }


def search_workspace(query: str, is_regex: bool = False, root: str | None = None) -> dict[str, Any]:
    """Search text files under the root for a literal or regex pattern."""
    query = (query or "").strip()
    if not query:
        raise CouncilError("Search query is required.")
    if len(query) > 300:
        raise CouncilError("Search query must be 300 characters or fewer.")
    if is_regex:
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as error:
            raise CouncilError(f"Invalid regular expression: {error}") from error
    else:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    root_path = resolve_root(root)
    matches: list[dict[str, Any]] = []
    truncated = False
    for current, dirs, files in os.walk(root_path, topdown=True):
        dirs[:] = [d for d in dirs if not _is_ignored_dir(d)]
        for name in files:
            if len(matches) >= WORKSPACE_SEARCH_MAX_RESULTS:
                truncated = True
                break
            if name.startswith("."):
                continue
            path = Path(current) / name
            if path.suffix.lower() in BINARY_SUFFIXES or not _is_text_file(path):
                continue
            try:
                if path.stat().st_size > WORKSPACE_MAX_FILE_BYTES:
                    continue
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if pattern.search(line):
                            matches.append({
                                "path": path.relative_to(root_path).as_posix(),
                                "line": line_number,
                                "text": line.strip()[:240],
                            })
                            if len(matches) >= WORKSPACE_SEARCH_MAX_RESULTS:
                                truncated = True
                                break
            except OSError:
                continue
    return {"query": query, "matches": matches, "truncated": truncated}


# ── Staged writes (diff first, apply after confirmation) ─────────────────────

def _unified_diff(path: Path, old: str, new: str, root_path: Path) -> str:
    rel = path.relative_to(root_path).as_posix() if path.is_relative_to(root_path) else str(path)
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
    )
    return "".join(diff)


def stage_write(relative_path: str, content: Any, root: str | None = None) -> dict[str, Any]:
    """Build the diff that writing `content` would produce. Nothing is written."""
    if not isinstance(content, str):
        raise CouncilError("File content must be text.")
    if len(content.encode("utf-8")) > WORKSPACE_MAX_FILE_BYTES:
        raise CouncilError(f"New content exceeds {WORKSPACE_MAX_FILE_BYTES:,} bytes.")
    root_path = resolve_root(root)
    path = resolve_in_workspace(relative_path, root_path)
    if path.exists() and not path.is_file():
        raise CouncilError(f"Target exists and is not a file: {relative_path}")
    old = ""
    if path.exists():
        if not _is_text_file(path):
            raise CouncilError(f"Refusing to modify a binary file: {relative_path}")
        old = path.read_text(encoding="utf-8", errors="replace")
    diff = _unified_diff(path, old, content, root_path)
    return {
        "path": path.relative_to(root_path).as_posix(),
        "diff": diff,
        "is_new": not path.exists(),
        "old_bytes": len(old.encode("utf-8")),
        "new_bytes": len(content.encode("utf-8")),
    }


def apply_write(relative_path: str, content: str, root: str | None = None) -> dict[str, Any]:
    """Write staged content. Called only after the user approves the diff."""
    root_path = resolve_root(root)
    path = resolve_in_workspace(relative_path, root_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": path.relative_to(root_path).as_posix(), "written": True,
            "bytes": len(content.encode("utf-8"))}


def stage_edit(relative_path: str, find: Any, replace: Any, root: str | None = None) -> dict[str, Any]:
    """Stage an exact-string replacement; `find` must occur exactly once."""
    if not isinstance(find, str) or not find:
        raise CouncilError("edit_file requires a non-empty 'find' string.")
    if not isinstance(replace, str):
        raise CouncilError("edit_file 'replace' must be text.")
    root_path = resolve_root(root)
    path = resolve_in_workspace(relative_path, root_path)
    if not path.is_file():
        raise CouncilError(f"File not found: {relative_path}")
    if not _is_text_file(path):
        raise CouncilError(f"Refusing to modify a binary file: {relative_path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    occurrences = text.count(find)
    if occurrences == 0:
        raise CouncilError(f"edit_file: 'find' text not found in {relative_path}. Re-read the file and copy the exact snippet.")
    if occurrences > 1:
        raise CouncilError(f"edit_file: 'find' text occurs {occurrences} times in {relative_path}; include more surrounding lines so it is unique.")
    new_text = text.replace(find, replace, 1)
    diff = _unified_diff(path, text, new_text, root_path)
    return {
        "path": path.relative_to(root_path).as_posix(),
        "diff": diff,
        "is_new": False,
        "old_bytes": len(text.encode("utf-8")),
        "new_bytes": len(new_text.encode("utf-8")),
    }


def apply_edit(relative_path: str, find: str, replace: str, root: str | None = None) -> dict[str, Any]:
    """Apply an exact-string replacement. Called only after user approval;
    re-validates so a file changed between staging and approval cannot be
    modified in the wrong place."""
    root_path = resolve_root(root)
    path = resolve_in_workspace(relative_path, root_path)
    if not path.is_file():
        raise CouncilError(f"File not found: {relative_path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.count(find) != 1:
        raise CouncilError(f"edit_file: staged snippet no longer matches {relative_path} exactly once; nothing written.")
    new_text = text.replace(find, replace, 1)
    path.write_text(new_text, encoding="utf-8")
    return {"path": path.relative_to(root_path).as_posix(), "written": True,
            "bytes": len(new_text.encode("utf-8"))}


# ── Commands ─────────────────────────────────────────────────────────────────

def validate_command(command: Any) -> str:
    """Validate a shell command that will be shown for user approval."""
    if isinstance(command, list):
        # Keep compatibility with older model prompts and clients.
        if not command or len(command) > 40 or any(not isinstance(item, str) for item in command):
            raise CouncilError("run_command requires a command string or a non-empty argument list.")
        command = shlex.join(command)
    if not isinstance(command, str) or not command.strip() or len(command) > 2_000:
        raise CouncilError("run_command requires a non-empty command string (max 2,000 characters).")
    command = command.strip()
    try:
        tokens = shlex.split(command)
    except ValueError as error:
        raise CouncilError(f"Invalid command quoting: {error}") from error
    if not tokens:
        raise CouncilError("run_command requires a non-empty command.")
    if tokens[0] not in ALLOWED_COMMAND_EXECUTABLES:
        raise CouncilError(
            f"Command '{tokens[0]}' is not allowlisted. Allowed starting commands: {', '.join(sorted(ALLOWED_COMMAND_EXECUTABLES))}."
        )
    lowered = {token.lower() for token in tokens}
    if lowered & FORBIDDEN_COMMAND_TOKENS:
        raise CouncilError("run_command refuses destructive subcommands.")
    if "\n" in command or "\r" in command:
        raise CouncilError("run_command must be a single line.")
    return command


def _local_probe_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise CouncilError("probe_url must be a local HTTP URL containing {host} and {port}.")
    if "{port}" not in value:
        raise CouncilError("probe_url must include the {port} placeholder for an independent server check.")
    template = value.replace("{host}", "127.0.0.1").replace("{port}", "49152")
    parsed = urllib.parse.urlsplit(template)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise CouncilError("probe_url must target localhost or 127.0.0.1.")
    try:
        parsed.port
    except ValueError as error:
        raise CouncilError("probe_url has an invalid port.") from error
    return value


def _server_responds(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5):
            return True
    except urllib.error.HTTPError:
        # A 4xx/5xx response still proves this process served an HTTP response.
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _run_server_probe(command: str, root_path: Path, probe_url: str) -> dict[str, Any]:
    if "{port}" not in command:
        raise CouncilError("A server probe command must include the {port} placeholder.")
    checked_url = _local_probe_url(probe_url)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    shell_command = command.replace("{host}", "127.0.0.1").replace("{port}", str(port))
    url = checked_url.replace("{host}", "127.0.0.1").replace("{port}", str(port))
    started = time.perf_counter()
    timed_out = False
    ready = False
    process: subprocess.Popen | None = None
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as output:
        try:
            process = subprocess.Popen(
                shell_command,
                cwd=str(root_path),
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
                shell=True,
                start_new_session=(os.name == "posix"),
            )
            deadline = time.monotonic() + WORKSPACE_SERVER_START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                if _server_responds(url):
                    ready = True
                    break
                time.sleep(0.25)
            else:
                timed_out = True
        except OSError as error:
            raise CouncilError(f"Could not start project server: {error}") from error
        finally:
            if process is not None and process.poll() is None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                    process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except OSError:
                        pass
                    process.wait(timeout=3)
        output.seek(0)
        stdout = output.read()
    elapsed_ms = round((time.perf_counter() - started) * 1_000)
    if ready:
        stdout = f"Project responded at {url}; the preflight server was stopped.\n{stdout}"
        code = 0
    else:
        code = 124 if timed_out else process.returncode if process is not None else 1
    stdout, stdout_cut = _cap_output(stdout)
    return {
        "command": shell_command,
        "stdout": stdout,
        "stderr": "",
        "returncode": code,
        "timed_out": timed_out,
        "duration_ms": elapsed_ms,
        "truncated": stdout_cut,
        "probe_url": url,
    }


def run_command(command: Any, root: str | None = None, probe_url: Any = None) -> dict[str, Any]:
    """Run an approved shell command, or start and probe a local server."""
    shell_command = validate_command(command)
    root_path = resolve_root(root)
    if probe_url is not None:
        return _run_server_probe(shell_command, root_path, probe_url)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            shell_command,
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=WORKSPACE_COMMAND_TIMEOUT_SECONDS,
            check=False,
            shell=True,
        )
        stdout, stderr, code, timed_out = completed.stdout, completed.stderr, completed.returncode, False
    except subprocess.TimeoutExpired as error:
        stdout = (error.stdout or b"").decode("utf-8", errors="replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = (error.stderr or b"").decode("utf-8", errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
        code, timed_out = 124, True
    except OSError as error:
        raise CouncilError(f"Could not run command: {error}") from error
    elapsed_ms = round((time.perf_counter() - started) * 1_000)
    stdout, stdout_cut = _cap_output(stdout)
    stderr, stderr_cut = _cap_output(stderr)
    return {
        "command": shell_command,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": code,
        "timed_out": timed_out,
        "duration_ms": elapsed_ms,
        "truncated": stdout_cut or stderr_cut,
    }


def _cap_output(value: str) -> tuple[str, bool]:
    if len(value) <= WORKSPACE_COMMAND_OUTPUT_CHARS:
        return value, False
    return value[:WORKSPACE_COMMAND_OUTPUT_CHARS].rstrip() + "\n…[output truncated]", True
