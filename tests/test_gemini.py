import urllib.error

import pytest

from app.core.exceptions import ProviderError
from app.services import providers
from app.services.extractors import extract_gemini_text, usage_fields
from app.services.gemini import gemini_models
from app.services.security import provider_ready


def _gemini_response(text: str = "hello", **usage) -> dict:
    response = {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
    }
    if usage:
        response["usageMetadata"] = usage
    return response


def test_extract_gemini_text_joins_candidate_parts():
    response = {
        "candidates": [{"content": {"parts": [{"text": "first"}, {"text": " second"}]}}],
    }
    assert extract_gemini_text(response) == "first\nsecond"


def test_extract_gemini_text_raises_without_text():
    with pytest.raises(ProviderError):
        extract_gemini_text({})


def test_usage_fields_normalizes_gemini_counters():
    usage = usage_fields({"usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4,
                                            "totalTokenCount": 14}}, "gemini")
    assert usage == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}


def test_call_gemini_sends_generate_content_request(monkeypatch):
    seen = {}

    def fake_request(method, url, *, payload=None, headers=None, timeout=75):
        seen.update({"method": method, "url": url, "payload": payload, "headers": headers})
        return _gemini_response("answer", totalTokenCount=7)

    monkeypatch.setattr(providers, "request_json", fake_request)
    text, usage = providers.call_gemini(
        {"model": "gemini-2.5-flash", "api_key": "test-key"},
        "What is 2+2?", "You are helpful.", 100, 0.3,
    )

    assert text == "answer"
    assert usage == {"total_tokens": 7}
    assert seen["url"] == ("https://generativelanguage.googleapis.com/v1beta/models/"
                           "gemini-2.5-flash@generateContent")
    assert seen["headers"] == {"x-goog-api-key": "test-key"}
    assert seen["payload"]["system_instruction"] == {"parts": [{"text": "You are helpful."}]}
    assert seen["payload"]["contents"] == [{"role": "user", "parts": [{"text": "What is 2+2?"}]}]
    assert seen["payload"]["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 100}


def test_call_gemini_uses_environment_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    def fake_request(method, url, *, payload=None, headers=None, timeout=75):
        assert headers == {"x-goog-api-key": "env-key"}
        return _gemini_response("ok")

    monkeypatch.setattr(providers, "request_json", fake_request)
    text, _ = providers.call_gemini({"model": "gemini-2.5-flash", "api_key": ""}, "q", "i", 10, 0)
    assert text == "ok"


def test_call_gemini_requires_a_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        providers.call_gemini({"model": "gemini-2.5-flash"}, "q", "i", 10, 0)


def test_agent_messages_map_roles(monkeypatch):
    seen = {}

    def fake_request(method, url, *, payload=None, headers=None, timeout=75):
        seen["payload"] = payload
        return _gemini_response("done")

    monkeypatch.setattr(providers, "request_json", fake_request)
    messages = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "step one"},
        {"role": "assistant", "content": "did step one"},
        {"role": "user", "content": "step two"},
    ]
    deltas = []
    text, _ = providers.call_agent_messages("gemini", {"model": "m", "api_key": "k"},
                                            messages, 50, 0.1, deltas.append, num_ctx=1024)
    assert text == "done"
    assert deltas == ["done"]
    assert seen["payload"]["system_instruction"] == {"parts": [{"text": "be brief"}]}
    assert seen["payload"]["contents"] == [
        {"role": "user", "parts": [{"text": "step one"}]},
        {"role": "model", "parts": [{"text": "did step one"}]},
        {"role": "user", "parts": [{"text": "step two"}]},
    ]


def test_gemini_models_filters_and_strips_prefix(monkeypatch):
    def fake_request(method, url, *, payload=None, headers=None, timeout=75):
        assert method == "GET"
        assert headers == {"x-goog-api-key": "k"}
        return {"models": [
            {"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash",
             "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-1", "displayName": "Embedding",
             "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/legacy-no-methods", "displayName": "Legacy"},
        ]}

    monkeypatch.setattr("app.services.gemini.request_json", fake_request)
    data = gemini_models({"api_key": "k"})
    assert [model["id"] for model in data["models"]] == ["gemini-2.5-flash", "legacy-no-methods"]
    assert data["models"][0]["name"] == "Gemini 2.5 Flash"


def test_provider_ready_reports_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reason = provider_ready("gemini", {"model": "gemini-2.5-flash"}, require_enabled=True)
    assert reason == "No API key supplied"


def test_provider_ready_accepts_environment_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    reason = provider_ready("gemini", {"model": "gemini-2.5-flash"}, require_enabled=True)
    assert reason is None
