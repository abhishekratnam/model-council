import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import CHAIR_INSTRUCTIONS, COMPACTION_NUM_CTX, settings
from app.core.exceptions import ProviderError
from app.core.memory import memory_store
from app.main import app
from app.services import council, compaction


class FakeRedis:
    """Minimal in-memory stand-in for the redis-py client surface MemoryStore uses."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.strings: dict[str, str] = {}

    def ping(self):
        return True

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        length = len(items)
        start = start + length if start < 0 else start
        end = end + length if end < 0 else end
        self.lists[key] = items[start:end + 1] if start <= end else []

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]

    def lset(self, key, index, value):
        self.lists[key][index] = value

    def lrem(self, key, count, value):
        items = self.lists.get(key, [])
        if value in items:
            items.remove(value)

    def llen(self, key):
        return len(self.lists.get(key, []))

    def ttl(self, key):
        return 86400

    def delete(self, *keys):
        for key in keys:
            self.lists.pop(key, None)
            self.strings.pop(key, None)

    def get(self, key):
        return self.strings.get(key)

    def set(self, key, value, ex=None):
        self.strings[key] = value

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.ops.append((name, args, kwargs))
            return self
        return record

    def execute(self):
        for name, args, kwargs in self.ops:
            getattr(self.client, name)(*args, **kwargs)
        self.ops = []


@pytest.fixture
def fake_memory(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(memory_store, "client", fake)
    monkeypatch.setattr(memory_store, "available", True)
    return fake


def seed_rounds(fake: FakeRedis, session_id: str, count: int) -> None:
    key = f"model_council:session:{session_id}"
    for i in range(count):
        fake.rpush(key, json.dumps({
            "round_id": f"r{i}",
            "question": f"question {i}",
            "members": [{"provider": "openai", "label": "OpenAI",
                         "status": "complete", "text": f"answer {i}"}],
            "revision": None,
            "synthesis": {"answer": f"synthesis {i}"},
        }))


def ollama_payload() -> dict:
    return {"providers": {"ollama": {"enabled": True, "model": "fake-local-model"}}}


# ── MemoryStore summary behaviour ────────────────────────────────────────────

def test_build_context_includes_summary_and_skips_covered_rounds(fake_memory) -> None:
    seed_rounds(fake_memory, "s1", 4)
    memory_store.store_summary("s1", {"summary": "DISTILLED FACTS", "covered_round_ids": ["r0", "r1"]})
    context = memory_store.build_context("s1")
    assert "DISTILLED FACTS" in context
    assert "question 2" in context and "question 3" in context
    assert "question 0" not in context and "question 1" not in context


def test_summary_survives_max_rounds_trim(fake_memory) -> None:
    memory_store.store_summary("s2", {"summary": "EARLY CONTEXT", "covered_round_ids": ["r0"]})
    seed_rounds(fake_memory, "s2", 1)
    for i in range(9):  # overflows max_rounds=8, trimming r0 away
        memory_store.store_round("s2", f"new{i}", f"later question {i}", [])
    context = memory_store.build_context("s2")
    assert "EARLY CONTEXT" in context
    assert "question 0" not in context


def test_clear_session_removes_summary(fake_memory) -> None:
    seed_rounds(fake_memory, "s3", 2)
    memory_store.store_summary("s3", {"summary": "X", "covered_round_ids": ["r0"]})
    assert memory_store.clear_session("s3") is True
    assert memory_store.load_summary("s3") is None
    assert memory_store.load_history("s3") == []


def test_compaction_candidates_keep_newest_uncovered(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MODEL_COUNCIL_COMPACTION_KEEP_ROUNDS", 2)
    rounds = [{"round_id": f"r{i}"} for i in range(5)]
    summary = {"summary": "old", "covered_round_ids": ["r0"]}
    candidates = compaction.compaction_candidates(rounds, summary)
    assert [r["round_id"] for r in candidates] == ["r1", "r2"]
    assert compaction.compaction_candidates(rounds[:3], summary) == []


# ── Compaction service ───────────────────────────────────────────────────────

def test_compaction_triggered_by_trim_pressure(fake_memory, monkeypatch) -> None:
    seed_rounds(fake_memory, "c1", 8)  # len >= max_rounds - 1 forces compaction
    calls = []

    def fake_ollama(config, messages, max_tokens, temperature, on_delta, **kwargs):
        calls.append(kwargs)
        return "DISTILLED SUMMARY", {"prompt_eval_count": 100, "eval_count": 40}

    monkeypatch.setattr(compaction, "call_ollama_messages", fake_ollama)
    record = compaction.compact_session_memory(ollama_payload(), "c1")
    assert record is not None and record["summary"] == "DISTILLED SUMMARY"
    assert record["covered_round_ids"] == [f"r{i}" for i in range(6)]  # newest 2 stay verbatim
    assert calls[0]["num_ctx"] == COMPACTION_NUM_CTX
    assert calls[0]["format_json"] is False
    stored = memory_store.load_summary("c1")
    assert stored["summary"] == "DISTILLED SUMMARY"
    context = memory_store.build_context("c1")
    assert "DISTILLED SUMMARY" in context and "question 0" not in context


def test_compaction_triggered_by_char_threshold(fake_memory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "MODEL_COUNCIL_COMPACTION_THRESHOLD_CHARS", 10)
    seed_rounds(fake_memory, "c2", 3)
    monkeypatch.setattr(compaction, "call_ollama_messages",
                        lambda *a, **k: ("SHORT SUMMARY", {}))
    record = compaction.compact_session_memory(ollama_payload(), "c2")
    assert record is not None
    assert record["covered_round_ids"] == ["r0"]


def test_no_compaction_below_threshold(fake_memory, monkeypatch) -> None:
    seed_rounds(fake_memory, "c3", 3)  # small context, no trim pressure

    def fail(*args, **kwargs):
        raise AssertionError("compaction must not run below the threshold")

    monkeypatch.setattr(compaction, "call_ollama_messages", fail)
    assert compaction.compact_session_memory(ollama_payload(), "c3") is None
    assert memory_store.load_summary("c3") is None


def test_compaction_skipped_without_ollama(fake_memory, monkeypatch) -> None:
    seed_rounds(fake_memory, "c4", 8)

    def fail(*args, **kwargs):
        raise AssertionError("compaction must not run without a local model")

    monkeypatch.setattr(compaction, "call_ollama_messages", fail)
    assert compaction.compact_session_memory({"providers": {}}, "c4") is None
    assert memory_store.load_summary("c4") is None


def test_compaction_disabled(fake_memory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "MODEL_COUNCIL_COMPACTION_ENABLED", False)
    seed_rounds(fake_memory, "c5", 8)
    assert compaction.compact_session_memory(ollama_payload(), "c5") is None
    assert memory_store.load_summary("c5") is None


def test_compaction_failure_keeps_history(fake_memory, monkeypatch) -> None:
    seed_rounds(fake_memory, "c6", 8)

    def broken(*args, **kwargs):
        raise ProviderError("local model unreachable")

    monkeypatch.setattr(compaction, "call_ollama_messages", broken)
    events = []
    assert compaction.compact_session_memory(ollama_payload(), "c6", emit=events.append) is None
    assert memory_store.load_summary("c6") is None
    assert len(memory_store.load_history("c6")) == 8
    assert any(e["type"] == "compaction_failed" for e in events)


def test_rolling_compaction_merges_previous_summary(fake_memory, monkeypatch) -> None:
    seed_rounds(fake_memory, "c7", 8)
    memory_store.store_summary("c7", {"summary": "FIRST PASS", "covered_round_ids": ["r0", "r1"]})
    seen = {}

    def fake_ollama(config, messages, max_tokens, temperature, on_delta, **kwargs):
        seen["transcript"] = messages[-1]["content"]
        return "SECOND PASS", {}

    monkeypatch.setattr(compaction, "call_ollama_messages", fake_ollama)
    record = compaction.compact_session_memory(ollama_payload(), "c7")
    assert record["covered_round_ids"] == [f"r{i}" for i in range(6)]
    assert "FIRST PASS" in seen["transcript"]
    assert "question 2" in seen["transcript"]
    assert "question 6" not in seen["transcript"]  # newest uncovered rounds stay verbatim


# ── End-to-end through the council WebSocket ─────────────────────────────────

def test_council_round_compacts_memory(fake_memory, monkeypatch) -> None:
    seed_rounds(fake_memory, "ws-compact", 7)

    def fake_provider(provider, config, prompt, instructions, max_tokens, temperature):
        if instructions == CHAIR_INSTRUCTIONS:
            return json.dumps({"agreement": "full", "conflicts": [],
                               "answer": "The answer is 42.", "confidence": "high"}), {"total_tokens": 12}
        return f"{provider} says 42", {"total_tokens": 12}

    monkeypatch.setattr(council, "call_provider", fake_provider)
    monkeypatch.setattr(council, "ollama_relay_call", lambda *a, **k: ("ollama says 42", {}))
    monkeypatch.setattr(compaction, "call_ollama_messages",
                        lambda *a, **k: ("WS DISTILLED SUMMARY", {}))

    request = {
        "action": "ask",
        "question": "What is the answer?",
        "session_id": "ws-compact",
        "providers": {
            "openai": {"enabled": True, "model": "fake-openai", "api_key": "fake-key"},
            "anthropic": {"enabled": True, "model": "fake-claude", "api_key": "fake-key"},
            "ollama": {"enabled": True, "model": "fake-local-model"},
        },
        "chair_provider": "openai",
    }

    events = []
    with TestClient(app) as client:
        with client.websocket_connect("/api/council/stream") as websocket:
            websocket.send_json(request)
            while True:
                event = websocket.receive_json()
                events.append(event)
                if event.get("type") == "round_complete":
                    result = event["result"]
                    break

    assert result["synthesis"]["answer"] == "The answer is 42."
    types = [e.get("type") for e in events]
    assert "compaction_start" in types and "compaction_complete" in types
    summary = memory_store.load_summary("ws-compact")
    assert summary["summary"] == "WS DISTILLED SUMMARY"
    assert "r0" in summary["covered_round_ids"]
    assert "WS DISTILLED SUMMARY" in memory_store.build_context("ws-compact")


def test_memory_endpoint_returns_summary(client: TestClient, fake_memory) -> None:
    memory_store.store_summary("endpoint-session", {"summary": "PERSISTED", "covered_round_ids": []})
    response = client.get("/api/memory/endpoint-session")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["summary"] == "PERSISTED"
