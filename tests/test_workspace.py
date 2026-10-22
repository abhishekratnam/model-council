import socket
from pathlib import Path

import pytest

from app.core.exceptions import CouncilError
from app.services import workspace


def test_read_file_ranges_and_rejects_binary_files(
    workspace_root: Path,
) -> None:
    (workspace_root / "sample.txt").write_text("one\ntwo\nthree\n")
    (workspace_root / "image.png").write_bytes(b"\x89PNG\x00data")

    result = workspace.read_file("sample.txt", offset=2, limit=1, root=str(workspace_root))
    assert result["content"] == "two"
    assert result["start_line"] == 2
    assert result["end_line"] == 2
    assert result["total_lines"] == 3
    assert result["truncated"] is True

    with pytest.raises(CouncilError, match="binary"):
        workspace.read_file("image.png", root=str(workspace_root))


def test_search_supports_regex_and_rejects_invalid_patterns(workspace_root: Path) -> None:
    (workspace_root / "notes.txt").write_text("item 1\nitem 20\nother\n")
    matches = workspace.search_workspace(r"item \d+", is_regex=True, root=str(workspace_root))
    assert [match["line"] for match in matches["matches"]] == [1, 2]

    with pytest.raises(CouncilError, match="Invalid regular expression"):
        workspace.search_workspace("[", is_regex=True, root=str(workspace_root))


def test_staged_edit_requires_unique_text_and_revalidates_on_apply(
    workspace_root: Path,
) -> None:
    target = workspace_root / "config.py"
    target.write_text("mode = 'old'\n")
    staged = workspace.stage_edit("config.py", "'old'", "'new'", root=str(workspace_root))
    assert "-mode = 'old'" in staged["diff"]
    assert "+mode = 'new'" in staged["diff"]
    assert target.read_text() == "mode = 'old'\n"

    workspace.apply_edit("config.py", "'old'", "'new'", root=str(workspace_root))
    assert target.read_text() == "mode = 'new'\n"

    target.write_text("mode = 'new'\nmode = 'new'\n")
    with pytest.raises(CouncilError, match="occurs 2 times"):
        workspace.stage_edit("config.py", "mode = 'new'", "mode = 'flag'", root=str(workspace_root))


def test_write_stage_apply_and_path_jail(workspace_root: Path) -> None:
    staged = workspace.stage_write("nested/new.txt", "hello\n", root=str(workspace_root))
    assert staged["is_new"] is True
    assert not (workspace_root / "nested" / "new.txt").exists()

    workspace.apply_write("nested/new.txt", "hello\n", root=str(workspace_root))
    assert (workspace_root / "nested" / "new.txt").read_text() == "hello\n"

    with pytest.raises(CouncilError, match="cannot contain"):
        workspace.stage_write("../outside.txt", "no", root=str(workspace_root))


def test_command_validation_and_execution(workspace_root: Path) -> None:
    result = workspace.run_command(
        ["python3", "-c", "print('command-ok')"], root=str(workspace_root)
    )
    assert result["returncode"] == 0
    assert "command-ok" in result["stdout"]
    assert result["timed_out"] is False

    with pytest.raises(CouncilError, match="not allowlisted"):
        workspace.validate_command("sh -c 'echo unsafe'")
    assert workspace.validate_command("python3 -c 'print(1); print(2)'" ).startswith("python3")
    assert workspace.validate_command("python3 -m pytest -q && npm test") == "python3 -m pytest -q && npm test"


def test_server_probe_uses_fresh_loopback_port_and_stops_process(
    workspace_root: Path,
) -> None:
    # Some CI/sandbox environments deny loopback sockets entirely. Keep the
    # real server lifecycle check enabled wherever the host permits binding.
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("host environment does not permit loopback socket binding")

    result = workspace.run_command(
        ["python3", "-m", "http.server", "{port}", "--bind", "{host}"],
        root=str(workspace_root),
        probe_url="http://{host}:{port}/",
    )
    assert result["returncode"] == 0
    assert result["timed_out"] is False
    assert "Project responded at http://127.0.0.1:" in result["stdout"]
    assert "stopped" in result["stdout"]
    assert result["probe_url"].startswith("http://127.0.0.1:")


def test_server_probe_rejects_non_loopback_targets(workspace_root: Path) -> None:
    with pytest.raises(CouncilError, match="target localhost"):
        workspace.run_command(
            ["python3", "-m", "http.server", "{port}"],
            root=str(workspace_root),
            probe_url="https://example.com:{port}/",
        )
