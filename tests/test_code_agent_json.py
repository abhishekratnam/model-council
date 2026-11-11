import json

import pytest

from app.core.exceptions import ProviderError
from app.services import code_agent, providers


def test_parse_action_reads_plain_json():
    assert code_agent._parse_action('{"action": "done", "summary": "ok"}') == {
        "action": "done", "summary": "ok"
    }


def test_parse_action_skips_leading_prose():
    text = 'Sure! Here is the action:\n{"action": "list_tree", "path": "src"}'
    assert code_agent._parse_action(text)["action"] == "list_tree"


def test_parse_action_returns_first_complete_object_not_a_merged_blob():
    text = '{"action": "search", "query": "a"}\n{"action": "done"}'
    parsed = code_agent._parse_action(text)
    assert parsed == {"action": "search", "query": "a"}


def test_parse_action_repairs_code_fences():
    text = '```json\n{"action": "done", "summary": "all tests pass"}\n```'
    assert code_agent._parse_action(text)["summary"] == "all tests pass"


def test_parse_action_repairs_trailing_commas():
    text = '{"action": "read_file", "path": "main.py", "limit": 10,}'
    parsed = code_agent._parse_action(text)
    assert parsed == {"action": "read_file", "path": "main.py", "limit": 10}


def test_parse_action_repairs_smart_quotes():
    text = '{"action": “done”, "summary": "finished"}'
    assert code_agent._parse_action(text)["action"] == "done"


def test_parse_action_returns_none_for_garbage():
    assert code_agent._parse_action("no json at all") is None
    assert code_agent._parse_action('{"action": broken') is None
    assert code_agent._parse_action(None) is None


def test_parse_plan_handles_list_steps():
    plan = code_agent._parse_plan('{"plan": ["step one", "step two"]}')
    assert "1. step one" in plan and "2. step two" in plan


def test_agent_model_call_passes_schema_to_ollama(monkeypatch):
    captured = {}

    def fake_call(config, messages, max_tokens, temperature, on_delta, **kwargs):
        captured.update(kwargs)
        return "text", {}

    monkeypatch.setattr(code_agent, "call_ollama_messages", fake_call)
    code_agent._call_agent_model(
        "ollama", {"model": "m"}, [], 100, 0, lambda *_: None,
        emit=lambda *_: None, browser_rpc_queue=None, delta_event_type="agent_delta",
        format_schema=code_agent.ACTION_JSON_SCHEMA,
    )
    assert captured["format_schema"] == code_agent.ACTION_JSON_SCHEMA


def test_agent_model_call_falls_back_when_schema_rejected(monkeypatch):
    calls = []

    def fake_call(config, messages, max_tokens, temperature, on_delta, **kwargs):
        calls.append(kwargs.get("format_schema"))
        if len(calls) == 1:
            raise ProviderError("Ollama HTTP 400: format must be one of json or jsonl.")
        return "text", {}

    monkeypatch.setattr(code_agent, "call_ollama_messages", fake_call)
    code_agent._call_agent_model(
        "ollama", {"model": "m"}, [], 100, 0, lambda *_: None,
        emit=lambda *_: None, browser_rpc_queue=None, delta_event_type="agent_delta",
        format_schema=code_agent.ACTION_JSON_SCHEMA,
    )
    assert calls == [code_agent.ACTION_JSON_SCHEMA, None]


def test_agent_model_call_keeps_other_errors(monkeypatch):
    def fake_call(config, messages, max_tokens, temperature, on_delta, **kwargs):
        raise ProviderError("Connection failed: refused.")

    monkeypatch.setattr(code_agent, "call_ollama_messages", fake_call)
    with pytest.raises(ProviderError):
        code_agent._call_agent_model(
            "ollama", {"model": "m"}, [], 100, 0, lambda *_: None,
            emit=lambda *_: None, browser_rpc_queue=None, delta_event_type="agent_delta",
            format_schema=code_agent.ACTION_JSON_SCHEMA,
        )


class _FakeResponse:
    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self._lines)


def test_call_ollama_messages_sends_schema_in_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout, context=None):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse([
            json.dumps({"message": {"content": "ok"}, "done": True,
                        "prompt_eval_count": 1, "eval_count": 2}),
        ])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    text, usage = providers.call_ollama_messages(
        {"model": "m", "base_url": "http://127.0.0.1:11434"},
        [{"role": "user", "content": "hi"}], 100, 0, lambda *_: None,
        num_ctx=2048, format_schema={"type": "object", "required": ["action"]},
    )
    assert text == "ok"
    assert usage["prompt_eval_count"] == 1
    assert captured["payload"]["format"] == {"type": "object", "required": ["action"]}
    assert captured["payload"]["options"]["num_ctx"] == 2048


def test_relay_message_forwards_schema(monkeypatch):
    emitted = []
    replies = [
        {"rpc": "ollama_chunk", "content": "ok"},
        {"rpc": "ollama_done", "usage": {}},
    ]

    def fake_get_for(request_id, timeout):
        return {**replies.pop(0), "request_id": request_id}

    relay_queue = type("Q", (), {"get_for": staticmethod(fake_get_for)})()
    providers.ollama_relay_messages(
        {"model": "m"}, [{"role": "user", "content": "hi"}], {},
        emitted.append, relay_queue, "agent_delta",
        format_json=True, format_schema={"type": "object"},
    )
    assert emitted[0]["format"] == {"type": "object"}
