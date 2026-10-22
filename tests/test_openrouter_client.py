import io
import urllib.error

from app.llm import openrouter_client


def test_empty_response_retries_then_falls_back(monkeypatch):
    requests = []
    responses = [
        *[{"choices": [{"message": {"content": ""}, "finish_reason": "length"}]} for _ in range(4)],
        {"choices": [{"message": {"content": "  answer  "}, "finish_reason": "stop"}], "usage": {"total_tokens": 3}},
    ]

    def fake_request(payload, api_key, timeout):
        requests.append((payload, api_key, timeout))
        return responses.pop(0)

    sleeps = []
    monkeypatch.setattr(openrouter_client, "_request", fake_request)
    monkeypatch.setattr(openrouter_client.time, "sleep", sleeps.append)
    text, result = openrouter_client.chat_completion(
        config={"model": "primary", "fallback_models": ["backup"], "api_key": "key"},
        messages=[{"role": "user", "content": "hello"}], max_tokens=10, temperature=0.2,
    )

    assert text == "answer"
    assert result["usage"]["total_tokens"] == 3
    assert [item[0]["model"] for item in requests] == ["primary"] * 4 + ["backup"]
    assert requests[0][0]["max_tokens"] == 2048
    assert sleeps == [1, 2, 4]


def test_retry_after_is_honored_and_api_key_comes_from_environment(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-key")

    def fake_request(payload, api_key, timeout):
        calls.append((payload, api_key))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                openrouter_client.URL, 429, "Too Many Requests", {"Retry-After": "7"},
                io.BytesIO(b'{"error":"rate limited"}'),
            )
        return {"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(openrouter_client, "_request", fake_request)
    monkeypatch.setattr(openrouter_client.time, "sleep", sleeps.append)
    text, _ = openrouter_client.chat_completion(
        config={"model": "primary", "fallback_models": []},
        messages=[{"role": "user", "content": "hello"}], max_tokens=2048, temperature=0,
    )

    assert text == "done"
    assert calls[0][1] == "environment-key"
    assert sleeps == [7.0]
