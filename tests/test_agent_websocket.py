import json
import queue
from threading import Event
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import code_agent


def _payload(root: Path, task: str) -> dict:
    return {
        "action": "code_task",
        "task": task,
        "root": str(root),
        "max_steps": 5,
        "providers": {"ollama": {"model": "test-coder"}},
    }


def _run_until_complete(client: TestClient, payload: dict, on_event=None) -> dict:
    with client.websocket_connect("/api/council/stream") as websocket:
        websocket.send_json(payload)
        while True:
            event = websocket.receive_json()
            if on_event:
                on_event(event, websocket)
            if event.get("type") == "agent_complete":
                return event["result"]


def test_agent_websocket_creates_and_resumes_session_handoff(
    workspace_root: Path, monkeypatch
) -> None:
    (workspace_root / "main.py").write_text("print('hello')\n")
    (workspace_root / "README.md").write_text(
        "# Example\n\n## Local development\nUse the documented localhost server.\n"
    )
    calls: list[list[dict[str, str]]] = []
    markdown_reads: list[str] = []
    original_read_file = code_agent.workspace.read_file

    def track_markdown_read(path, *args, **kwargs):
        if str(path).casefold().endswith((".md", ".markdown")):
            markdown_reads.append(str(path))
        return original_read_file(path, *args, **kwargs)
    responses = iter([
        json.dumps({"plan": ["Inspect the entry point", "Run the documented startup check"]}),
        json.dumps({"action": "done", "summary": "Baseline inspected."}),
        json.dumps({"plan": ["Review the previous handoff", "Continue the requested work"]}),
        json.dumps({"action": "done", "summary": "Continued successfully."}),
    ])

    def fake_model_call(config, messages, max_tokens, temperature, on_delta, **kwargs):
        calls.append([message.copy() for message in messages])
        response = next(responses)
        on_delta(response)
        return response, {"prompt_eval_count": 10, "eval_count": 5}

    monkeypatch.setattr(code_agent, "call_ollama_messages", fake_model_call)
    monkeypatch.setattr(code_agent.workspace, "read_file", track_markdown_read)

    def approve_plan(event, websocket):
        if event.get("type") == "agent_plan":
            websocket.send_json({
                "rpc": "agent_plan_review",
                "review_id": event["review_id"],
                "approved": True,
                "plan": event["plan"] + "\n3. Keep the existing public API compatible",
            })

    with TestClient(app) as client:
        first = _run_until_complete(
            client, _payload(workspace_root, "Inspect this project"), approve_plan
        )
        handoff = workspace_root / ".model_council" / "plans" / "last_session.md"
        assert first["ok"] is True
        assert first["plan_status"] == "approved"
        assert first["session_log"] == ".model_council/plans/last_session.md"
        assert handoff.is_file()
        assert "Baseline inspected." in handoff.read_text()

        second = _run_until_complete(
            client, _payload(workspace_root, "Continue the project"), approve_plan
        )
        assert second["ok"] is True

    first_plan_prompt = calls[0][1]["content"]
    first_action_prompt = calls[1][1]["content"]
    resumed_plan_prompt = calls[2][1]["content"]
    assert "CURRENT FILE TREE:" in first_plan_prompt
    assert "main.py" in first_plan_prompt
    assert "PREVIOUS AGENT SESSION LOG" in first_plan_prompt
    assert "No previous agent session log" in first_plan_prompt
    assert "PROJECT CATEGORY: python" in first_plan_prompt
    assert "Python project guidance" in first_plan_prompt
    assert "PROJECT CATEGORY: python" in first_action_prompt
    assert "Python project guidance" in first_action_prompt
    assert "USER-APPROVED IMPLEMENTATION PLAN" in first_action_prompt
    assert "Keep the existing public API compatible" in first_action_prompt
    assert "Baseline inspected." in resumed_plan_prompt
    assert "Use the documented localhost server." in first_plan_prompt
    assert "Use the documented localhost server." in first_action_prompt
    assert markdown_reads == ["README.md", "README.md"]


def test_agent_websocket_stops_when_mixed_project_category_is_unresolved(
    workspace_root: Path, monkeypatch
) -> None:
    (workspace_root / "Cargo.toml").write_text("[package]\nname = 'sample'\n")
    (workspace_root / "src").mkdir()
    (workspace_root / "src" / "main.rs").write_text("fn main() {}\n")
    (workspace_root / "package.json").write_text('{"scripts": {}}\n')
    (workspace_root / "web").mkdir()
    (workspace_root / "web" / "app.tsx").write_text("export default function App() {}\n")

    calls: list[list[dict[str, str]]] = []

    def fake_model_call(config, messages, max_tokens, temperature, on_delta, **kwargs):
        calls.append([message.copy() for message in messages])
        response = json.dumps({"plan": [
            "Ask the user to select a project category",
            "Wait for an explicit category in the reviewed plan",
        ]})
        on_delta(response)
        return response, {}

    monkeypatch.setattr(code_agent, "call_ollama_messages", fake_model_call)

    def approve_without_category(event, websocket):
        if event.get("type") == "agent_plan":
            websocket.send_json({
                "rpc": "agent_plan_review",
                "review_id": event["review_id"],
                "approved": True,
                "plan": event["plan"],
            })

    with TestClient(app) as client:
        result = _run_until_complete(
            client, _payload(workspace_root, "Improve the project"), approve_without_category
        )

    assert result["ok"] is False
    assert result["plan_status"] == "clarification_required"
    assert "still ambiguous" in result["summary"]
    assert len(calls) == 1
    assert "PROJECT CATEGORY: ambiguous" in calls[0][1]["content"]
    assert "candidate categories are javascript, rust" in calls[0][1]["content"]


def test_agent_websocket_stages_and_applies_approved_file_change(
    workspace_root: Path, monkeypatch
) -> None:
    responses = iter([
        json.dumps({"plan": ["Inspect the workspace", "Create the new module"]}),
        json.dumps({"action": "write_file", "path": "new.py", "content": "VALUE = 7\n"}),
        json.dumps({"action": "done", "summary": "Added new.py."}),
    ])

    def fake_model_call(config, messages, max_tokens, temperature, on_delta, **kwargs):
        response = next(responses)
        on_delta(response)
        return response, {}

    monkeypatch.setattr(code_agent, "call_ollama_messages", fake_model_call)

    def approve_plan_and_write(event, websocket):
        if event.get("type") == "agent_plan":
            websocket.send_json({
                "rpc": "agent_plan_review",
                "review_id": event["review_id"],
                "approved": True,
                "plan": event["plan"] + "\n3. Add VALUE = 7",
            })
        elif event.get("type") == "agent_confirm" and event.get("kind") == "write":
            websocket.send_json({
                "rpc": "agent_confirm",
                "confirm_id": event["confirm_id"],
                "approved": True,
            })

    with TestClient(app) as client:
        result = _run_until_complete(
            client, _payload(workspace_root, "Create a small module"), approve_plan_and_write
        )

    assert result["ok"] is True
    assert result["plan_status"] == "approved"
    assert "Add VALUE = 7" in result["plan"]
    assert result["applied_changes"] == ["new.py"]
    assert (workspace_root / "new.py").read_text() == "VALUE = 7\n"


def test_rejected_plan_stops_before_implementation(
    workspace_root: Path, monkeypatch
) -> None:
    calls = 0

    def fake_model_call(config, messages, max_tokens, temperature, on_delta, **kwargs):
        nonlocal calls
        calls += 1
        response = json.dumps({"plan": ["Inspect the code", "Change auth behavior"]})
        on_delta(response)
        return response, {}

    monkeypatch.setattr(code_agent, "call_ollama_messages", fake_model_call)

    def reject_plan(event, websocket):
        if event.get("type") == "agent_plan":
            websocket.send_json({
                "rpc": "agent_plan_review",
                "review_id": event["review_id"],
                "approved": False,
            })

    with TestClient(app) as client:
        result = _run_until_complete(
            client, _payload(workspace_root, "Change authentication"), reject_plan
        )

    assert result["ok"] is False
    assert result["plan_status"] == "rejected"
    assert "no implementation actions" in result["summary"]
    assert result["steps"] == []
    assert calls == 2
    assert not list(workspace_root.glob("*.py"))


def test_unanswered_plan_is_saved_approved_and_resumed(
    workspace_root: Path, monkeypatch, tmp_path: Path
) -> None:
    state_file = tmp_path / ".model_council" / "session_state.json"
    monkeypatch.setattr("app.session.pending_plan_path", lambda: state_file)
    monkeypatch.setattr(code_agent, "CODE_AGENT_PLAN_CONFIRM_TIMEOUT_SECONDS", 0)
    responses = iter([
        json.dumps({"plan": {"steps": ["Inspect files", "Run tests"], "files": [], "commands": []}}),
        json.dumps({"action": "done", "summary": "Resumed and completed."}),
    ])

    def fake_model_call(config, messages, max_tokens, temperature, on_delta, **kwargs):
        response = next(responses)
        on_delta(response)
        return response, {}

    monkeypatch.setattr(code_agent, "call_ollama_messages", fake_model_call)
    payload = _payload(workspace_root, "Resume the paused task")
    with TestClient(app) as client:
        paused = _run_until_complete(client, payload)
        assert paused["plan_status"] == "paused"
        assert state_file.is_file()
        saved = json.loads(state_file.read_text())
        assert saved["status"] == "paused"
        assert "api_key" not in saved

        listed = client.get("/api/agent/pending-plan").json()
        assert listed["pending"] is True
        approved = client.post(
            f"/api/agent/pending-plan/{saved['plan_id']}/decision", json={"decision": "approve"}
        )
        assert approved.status_code == 200
        resumed_payload = {**payload, "resume_plan_id": saved["plan_id"]}
        resumed = _run_until_complete(client, resumed_payload)

    assert resumed["ok"] is True
    assert resumed["plan_status"] == "approved"
    assert resumed["summary"] == "Resumed and completed."
    assert not state_file.exists()


def test_approved_scope_and_full_access_auto_run_only_allowed_actions(
    workspace_root: Path, monkeypatch
) -> None:
    events = []
    rpc_queue = queue.Queue()
    monkeypatch.setattr(
        code_agent.workspace,
        "run_command",
        lambda command, root, probe_url=None: {
            "command": command, "stdout": "ok", "stderr": "", "returncode": 0,
            "duration_ms": 1, "truncated": False, "timed_out": False,
        },
    )
    file_record = {"index": 1, "action": "write_file", "label": "Write file", "detail": ""}
    text, error = code_agent._execute_action(
        {"action": "write_file", "path": "planned.py", "content": "VALUE = 1\n"},
        events.append, rpc_queue, Event(), [], [], file_record, str(workspace_root),
        approval_scope=({"planned.py"}, set()),
    )
    assert not error
    assert (workspace_root / "planned.py").read_text() == "VALUE = 1\n"
    assert any(event.get("type") == "agent_auto_approved" and event.get("kind") == "write" for event in events)
    assert not any(event.get("type") == "agent_confirm" for event in events)

    events.clear()
    command_record = {"index": 2, "action": "run_command", "label": "Run command", "detail": ""}
    _, error = code_agent._execute_action(
        {"action": "run_command", "command": "python3 -c 'print(1)'"},
        events.append, rpc_queue, Event(), [], [], command_record, str(workspace_root),
        approval_scope=(set(), set()), full_access=True,
    )
    assert not error
    assert any(event.get("type") == "agent_auto_approved" and event.get("kind") == "command" for event in events)
    assert not any(event.get("type") == "agent_confirm" for event in events)

    events.clear()
    _, error = code_agent._execute_action(
        {"action": "run_command", "command": "python3 -c 'print(2)'"},
        lambda event: (events.append(event), rpc_queue.put({
            "rpc": "agent_confirm", "confirm_id": event.get("confirm_id"), "approved": True,
        }) if event.get("type") == "agent_confirm" else None),
        rpc_queue, Event(), [], [], command_record, str(workspace_root),
        approval_scope=(set(), set()), full_access=False,
    )
    assert not error
    assert any(event.get("type") == "agent_confirm" for event in events)
    assert code_agent._command_needs_extra_approval(
        "python3 -c 'from urllib.request import urlopen; urlopen(\"https://example.invalid\")'",
        str(workspace_root),
    )
    assert code_agent._command_needs_extra_approval(
        "python3 -c 'open(\"/etc/hosts\").read()'", str(workspace_root)
    )


def test_paused_plan_can_be_rejected_or_discarded(client, monkeypatch, tmp_path: Path) -> None:
    state_file = tmp_path / ".model_council" / "session_state.json"
    monkeypatch.setattr("app.session.pending_plan_path", lambda: state_file)
    from app.session import save_paused_plan

    for decision in ("reject", "discard"):
        saved = save_paused_plan({"task": "A paused task", "plan": "## Steps\n1. Inspect"})
        response = client.post(
            f"/api/agent/pending-plan/{saved['plan_id']}/decision", json={"decision": decision}
        )
        assert response.status_code == 200
        assert response.json()["status"] == ("rejected" if decision == "reject" else "discarded")
        assert not state_file.exists()
