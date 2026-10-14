import json
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
    calls: list[list[dict[str, str]]] = []
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
    assert "USER-APPROVED IMPLEMENTATION PLAN" in first_action_prompt
    assert "Keep the existing public API compatible" in first_action_prompt
    assert "Baseline inspected." in resumed_plan_prompt


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
    assert calls == 1
    assert not list(workspace_root.glob("*.py"))
