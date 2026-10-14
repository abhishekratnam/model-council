import json

from fastapi.testclient import TestClient

from app.core.config import CHAIR_INSTRUCTIONS
from app.main import app
from app.services import council


def test_council_websocket_runs_members_and_synthesizes(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_provider(provider, config, prompt, instructions, max_tokens, temperature):
        calls.append((provider, instructions))
        if instructions == CHAIR_INSTRUCTIONS:
            text = json.dumps({
                "agreement": "full",
                "conflicts": [],
                "answer": "The models agree: the answer is 42.",
                "confidence": "high",
            })
        else:
            text = f"{provider} says 42"
        return text, {"total_tokens": 12}

    monkeypatch.setattr(council, "call_provider", fake_provider)
    request = {
        "action": "ask",
        "question": "What is the answer?",
        "session_id": "e2e-test-session",
        "memory_enabled": False,
        "providers": {
            "openai": {"enabled": True, "model": "fake-openai", "api_key": "fake-key"},
            "anthropic": {"enabled": True, "model": "fake-claude", "api_key": "fake-key"},
        },
        "chair_provider": "openai",
    }

    with TestClient(app) as client:
        with client.websocket_connect("/api/council/stream") as websocket:
            websocket.send_json(request)
            while True:
                event = websocket.receive_json()
                if event.get("type") == "round_complete":
                    result = event["result"]
                    break

    assert {member["provider"] for member in result["members"] if member["status"] == "complete"} == {
        "openai", "anthropic"
    }
    assert result["synthesis"]["answer"] == "The models agree: the answer is 42."
    assert result["disagreement"]["agreement"] == "full"
    assert any(instructions == CHAIR_INSTRUCTIONS for _, instructions in calls)
