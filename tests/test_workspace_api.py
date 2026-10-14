from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings


def test_health_and_static_app(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["ollama_default"] == "http://127.0.0.1:11434"

    page = client.get("/")
    assert page.status_code == 200
    assert "Model Council" in page.text
    assert page.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in page.headers["content-security-policy"]


def test_workspace_root_tree_read_and_search(
    client: TestClient, workspace_root: Path
) -> None:
    (workspace_root / "app").mkdir()
    (workspace_root / "app" / "main.py").write_text("def hello():\n    return 'hello'\n")
    (workspace_root / ".env").write_text("SECRET=value\n")

    roots = client.get("/api/workspace/roots")
    assert roots.status_code == 200
    assert roots.json()["roots"] == [{"path": str(workspace_root), "exists": True}]

    tree = client.post("/api/workspace/tree", json={"root": str(workspace_root)})
    assert tree.status_code == 200
    assert {entry["path"] for entry in tree.json()["entries"]} == {"app", "app/main.py"}
    assert ".env" not in {entry["path"] for entry in tree.json()["entries"]}

    secret_search = client.post(
        "/api/workspace/search",
        json={"root": str(workspace_root), "query": "SECRET=value"},
    )
    assert secret_search.status_code == 200
    assert secret_search.json()["matches"] == []

    read = client.post(
        "/api/workspace/read",
        json={"root": str(workspace_root), "path": "app/main.py", "offset": 2, "limit": 1},
    )
    assert read.status_code == 200
    assert read.json()["start_line"] == 2
    assert read.json()["content"] == "    return 'hello'"

    search = client.post(
        "/api/workspace/search",
        json={"root": str(workspace_root), "query": "hello"},
    )
    assert search.status_code == 200
    assert search.json()["matches"] == [
        {"path": "app/main.py", "line": 1, "text": "def hello():"},
        {"path": "app/main.py", "line": 2, "text": "return 'hello'"},
    ]


def test_workspace_api_rejects_unsafe_paths_and_unconfigured_roots(
    client: TestClient, workspace_root: Path
) -> None:
    traversal = client.post(
        "/api/workspace/read",
        json={"root": str(workspace_root), "path": "../outside.txt"},
    )
    assert traversal.status_code == 400
    assert "relative to the workspace root" in traversal.json()["error"]

    dotfile = client.post(
        "/api/workspace/read",
        json={"root": str(workspace_root), "path": ".env"},
    )
    assert dotfile.status_code == 400

    other_root = client.post(
        "/api/workspace/tree",
        json={"root": str(workspace_root.parent)},
    )
    assert other_root.status_code == 400


def test_api_rejects_untrusted_browser_origin(client: TestClient, monkeypatch) -> None:
    # The repo's local .env may intentionally set MODEL_COUNCIL_ALLOWED_ORIGINS=*.
    # Exercise the default allowlist policy independently of that local override.
    monkeypatch.setattr(settings, "MODEL_COUNCIL_ALLOWED_ORIGINS", "")
    response = client.get("/api/health", headers={"Origin": "https://attacker.example"})
    assert response.status_code == 403
    assert "does not accept requests from this browser origin" in response.json()["error"]


def test_invalid_memory_session_is_rejected(client: TestClient) -> None:
    response = client.get("/api/memory/invalid%20session")
    assert response.status_code == 400
    assert "Session ID must be 1–128 alphanumeric characters" in response.json()["error"]
