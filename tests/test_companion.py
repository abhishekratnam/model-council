from pathlib import Path

from fastapi.testclient import TestClient

import app.companion as companion


def test_companion_pairing_and_selected_folder_operations(tmp_path: Path, monkeypatch) -> None:
    origin = "https://council.example"
    selected_root = tmp_path / "repo,with-comma"
    selected_root.mkdir()
    monkeypatch.setattr(companion, "_choose_folder", lambda: str(selected_root))
    app, _ = companion.create_companion_app(origin, pair_code="one-time-code")
    client = TestClient(app, base_url="http://localhost")
    origin_headers = {"Origin": origin}

    unauthorized = client.get("/status", headers=origin_headers)
    assert unauthorized.status_code == 401

    paired = client.post("/pair", headers=origin_headers, json={"code": "one-time-code"})
    assert paired.status_code == 200
    token = paired.json()["token"]
    auth_headers = {**origin_headers, "Authorization": f"Bearer {token}"}

    selected = client.post("/pick", headers=auth_headers)
    assert selected.status_code == 200
    assert selected.json() == {"selected": True, "root": str(selected_root)}

    tree = client.post("/workspace/list_tree", headers=auth_headers, json={})
    assert tree.status_code == 200
    assert tree.json()["entries"] == []

    staged = client.post(
        "/workspace/stage_write",
        headers=auth_headers,
        json={"path": "hello.py", "content": "print('hello')\n"},
    )
    assert staged.status_code == 200
    assert "hello.py" in staged.json()["diff"]
    assert not (tmp_path / "hello.py").exists()

    applied = client.post(
        "/workspace/apply_write",
        headers=auth_headers,
        json={"path": "hello.py", "content": "print('hello')\n"},
    )
    assert applied.status_code == 200
    assert (selected_root / "hello.py").read_text() == "print('hello')\n"

    staged_edit = client.post(
        "/workspace/stage_edit",
        headers=auth_headers,
        json={"path": "hello.py", "find": "hello", "replace": "world"},
    )
    assert staged_edit.status_code == 200
    applied_edit = client.post(
        "/workspace/apply_edit",
        headers=auth_headers,
        json={"path": "hello.py", "find": "hello", "replace": "world"},
    )
    assert applied_edit.status_code == 200
    assert applied_edit.json()["path"] == "hello.py"
    assert (selected_root / "hello.py").read_text() == "print('world')\n"

    rejected_origin = client.get("/status", headers={**auth_headers, "Origin": "https://attacker.example"})
    assert rejected_origin.status_code == 403

