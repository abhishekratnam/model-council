import json

from app.core.exceptions import ProviderError
from app.services import opencode, providers
from app.services.extractors import extract_openai_chat_text


def test_opencode_models_parses_and_detects_protocol(monkeypatch) -> None:
    captured = {}

    def fake_request_json(method, url, *, payload=None, headers=None, timeout=75):
        captured.update({"method": method, "url": url, "headers": headers})
        return {"data": [
            {"id": "gpt-6.1-sol", "name": "GPT 6.1 SOL", "api": {"responses": {}}},
            {"id": "kimi-k3", "name": "Kimi K3", "api": {"chat-completions": {}}},
            {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5", "api": {"messages": {}}},
            {"id": "unnamed-model"},
        ]}

    monkeypatch.setattr(opencode, "request_json", fake_request_json)
    result = opencode.opencode_models({"api_key": "oc_sk-test"})

    assert captured["url"] == "https://opencode.ai/inference/v1/models"
    assert captured["headers"] == {"Authorization": "Bearer oc_sk-test"}
    by_id = {model["id"]: model for model in result["models"]}
    assert by_id["gpt-6.1-sol"]["protocol"] == "responses"
    assert by_id["kimi-k3"]["protocol"] == "chat-completions"
    assert by_id["claude-sonnet-5-5"]["protocol"] == ""
    assert by_id["unnamed-model"]["name"] == "unnamed-model"
    assert len(result["models"]) == 4


def test_opencode_models_requires_key(monkeypatch) -> None:
    from app.core.exceptions import CouncilError

    def fail(*args, **kwargs):
        raise AssertionError("must not call the API without a key")

    monkeypatch.setattr(opencode, "request_json", fail)
    try:
        opencode.opencode_models({"api_key": "  "})
    except CouncilError as error:
        assert "required" in str(error)
    else:
        raise AssertionError("expected a CouncilError for a missing key")


def test_opencode_models_rejects_unexpected_shape(monkeypatch) -> None:
    monkeypatch.setattr(opencode, "request_json", lambda *a, **k: {"data": "nope"})
    try:
        opencode.opencode_models({"api_key": "oc_sk-test"})
    except ProviderError as error:
        assert "unexpected model list" in str(error)
    else:
        raise AssertionError("expected a ProviderError for a malformed response")


def test_extract_openai_chat_text_string_and_blocks() -> None:
    assert extract_openai_chat_text(
        {"choices": [{"message": {"content": "  plain text  "}}]}
    ) == "plain text"
    assert extract_openai_chat_text(
        {"choices": [{"message": {"content": [
            {"type": "text", "text": " first "},
            {"type": "text", "text": " second "},
        ]}}]}
    ) == "first\nsecond"


def test_call_opencode_responses_protocol(monkeypatch) -> None:
    calls = []

    def fake_request_json(method, url, *, payload=None, headers=None, timeout=75):
        calls.append({"method": method, "url": url, "payload": payload})
        return {"output_text": "OpenCode answered.", "usage": {"total_tokens": 40}}

    monkeypatch.setattr(providers, "request_json", fake_request_json)
    text, usage = providers.call_opencode(
        {"api_key": "oc_sk-test", "model": "gpt-6.1-sol", "protocol": "responses"},
        "What is 2+2?", "Be helpful.", 512, 0.4,
    )
    assert text == "OpenCode answered."
    assert usage == {"total_tokens": 40}
    assert calls[0]["url"] == "https://opencode.ai/inference/openai/v1/responses"
    assert calls[0]["payload"]["model"] == "gpt-6.1-sol"
    assert calls[0]["payload"]["input"] == [{"role": "user", "content": "What is 2+2?"}]


def test_call_opencode_chat_completions_protocol(monkeypatch) -> None:
    calls = []

    def fake_request_json(method, url, *, payload=None, headers=None, timeout=75):
        calls.append({"url": url, "payload": payload})
        return {"choices": [{"message": {"content": "Chat answer."}}], "usage": {"total_tokens": 25}}

    monkeypatch.setattr(providers, "request_json", fake_request_json)
    text, usage = providers.call_opencode(
        {"api_key": "oc_sk-test", "model": "kimi-k3", "protocol": "chat-completions"},
        "Hi", "System note.", 256, 0.3,
    )
    assert text == "Chat answer."
    assert usage == {"total_tokens": 25}
    assert calls[0]["url"] == "https://opencode.ai/inference/openai/v1/chat/completions"
    assert calls[0]["payload"]["messages"] == [
        {"role": "system", "content": "System note."},
        {"role": "user", "content": "Hi"},
    ]


def test_call_opencode_auto_falls_back_to_chat(monkeypatch) -> None:
    urls = []

    def fake_request_json(method, url, *, payload=None, headers=None, timeout=75):
        urls.append(url)
        if url.endswith("/responses"):
            raise ProviderError("Responses rejected this model (HTTP 404).")
        return {"choices": [{"message": {"content": "Fallback answer."}}]}

    monkeypatch.setattr(providers, "request_json", fake_request_json)
    text, _ = providers.call_opencode(
        {"api_key": "oc_sk-test", "model": "kimi-k3", "protocol": "auto"},
        "Hi", "System note.", 256, 0.3,
    )
    assert text == "Fallback answer."
    assert urls == ["https://opencode.ai/inference/openai/v1/responses",
                    "https://opencode.ai/inference/openai/v1/chat/completions"]


def test_call_opencode_requires_key() -> None:
    try:
        providers.call_opencode({"model": "gpt-6.1-sol"}, "Hi", "", 256, 0.3)
    except ProviderError as error:
        assert "API key" in str(error)
    else:
        raise AssertionError("expected a ProviderError for a missing key")


def test_call_opencode_missing_protocol_defaults_to_auto(monkeypatch) -> None:
    monkeypatch.setattr(providers, "request_json", lambda *a, **k:
                        {"output_text": "ok", "usage": {}})
    text, _ = providers.call_opencode(
        {"api_key": "oc_sk-test", "model": "gpt-6.1-sol"}, "Hi", "", 256, 0.3,
    )
    assert text == "ok"
