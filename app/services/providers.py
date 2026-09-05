import json
import ssl
import socket
import queue
import urllib.error
import urllib.request
from typing import Any
from app.core.config import DEFAULT_OLLAMA_BASE_URL, OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS
from app.core.exceptions import CouncilError, ProviderError
from app.services.http_client import request_json, error_detail
from app.services.extractors import extract_openai_text, extract_anthropic_text, extract_ollama_text, usage_fields
from app.services.security import clean_ollama_base_url, provider_model, custom_string_map, custom_response_url, scrub_secrets

def call_openai(config: dict[str, Any], question: str, instructions: str, max_tokens: int, temperature: float) -> tuple[str, dict[str, int]]:
    model = provider_model(config)
    api_key = str(config["api_key"]).strip()
    response = request_json(
        "POST",
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}"},
        payload={
            "model": model,
            "instructions": instructions,
            "input": [{"role": "user", "content": question}],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "store": False,
        },
    )
    return extract_openai_text(response), usage_fields(response, "openai")

def call_custom(config: dict[str, Any], question: str, instructions: str, max_tokens: int, temperature: float) -> tuple[str, dict[str, int]]:
    headers = custom_string_map(config.get("headers"), field="Custom headers")
    auth_type = config.get("auth_type", "bearer")
    api_key = config.get("api_key", "")
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {str(api_key).strip()}"
    elif auth_type == "api-key":
        headers["api-key"] = str(api_key).strip()
    response = request_json(
        "POST",
        custom_response_url(config),
        headers=headers,
        payload={
            "model": provider_model(config),
            "instructions": instructions,
            "input": [{"role": "user", "content": question}],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "store": False,
        },
    )
    return extract_openai_text(response), usage_fields(response, "custom")

def call_anthropic(config: dict[str, Any], question: str, instructions: str, max_tokens: int, temperature: float) -> tuple[str, dict[str, int]]:
    model = provider_model(config)
    api_key = str(config["api_key"]).strip()
    response = request_json(
        "POST",
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        payload={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": instructions,
            "messages": [{"role": "user", "content": question}],
        },
    )
    return extract_anthropic_text(response), usage_fields(response, "anthropic")

def call_ollama(config: dict[str, Any], question: str, instructions: str, max_tokens: int, temperature: float) -> tuple[str, dict[str, int]]:
    base_url = clean_ollama_base_url(config.get("base_url"))
    response = request_json(
        "POST",
        f"{base_url}/api/chat",
        payload={
            "model": provider_model(config),
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": question},
            ],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "keep_alive": "5m",
        },
    )
    return extract_ollama_text(response), usage_fields(response, "ollama")

def ollama_relay_call(
    config: dict[str, Any], 
    question: str, 
    instructions: str, 
    max_tokens: int, 
    temperature: float, 
    emit: Any,
    browser_rpc_queue: queue.Queue,
    delta_event_type: str = "member_delta",
    provider: str = "ollama"
) -> tuple[str, dict[str, int]]:
    print("FastAPI is sending RPC to browser to fetch Ollama...")
    emit({
        "type": "rpc_ollama_chat",
        "model": provider_model(config),
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": question}
        ],
        "options": {"temperature": temperature, "num_predict": max_tokens},
        "keep_alive": "5m"
    })
    
    chunks: list[str] = []
    final_usage: dict[str, int] = {}
    while True:
        try:
            msg = browser_rpc_queue.get(timeout=OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS)
        except queue.Empty:
            raise ProviderError("Browser took too long to respond from local Ollama.")
            
        rpc_type = msg.get("rpc")
        if rpc_type == "ollama_chunk":
            content = msg.get("content", "")
            if content:
                chunks.append(content)
                if delta_event_type == "member_delta":
                    emit({"type": "member_delta", "provider": provider, "delta": content})
                else:
                    emit({"type": delta_event_type, "delta": content})
        elif rpc_type == "ollama_done":
            final_usage = msg.get("usage", {})
            break
        elif rpc_type == "ollama_error":
            raise ProviderError(msg.get("error", "Browser failed to reach local Ollama"))
            
    text = "".join(chunks).strip()
    if not text:
        raise ProviderError("Ollama returned no text output.")
    return text, final_usage

def call_ollama_stream(
    config: dict[str, Any],
    question: str,
    instructions: str,
    max_tokens: int,
    temperature: float,
    on_delta: Any,
) -> tuple[str, dict[str, int]]:
    base_url = clean_ollama_base_url(config.get("base_url"))
    payload = {
        "model": provider_model(config),
        "stream": True,
        "think": False,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": question},
        ],
        "options": {"temperature": temperature, "num_predict": max_tokens},
        "keep_alive": "5m",
    }
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "application/x-ndjson", "Content-Type": "application/json"},
        method="POST",
    )
    chunks: list[str] = []
    final_response: dict[str, Any] | None = None
    try:
        context = ssl.create_default_context() if base_url.startswith("https://") else None
        with urllib.request.urlopen(
            request, timeout=OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS, context=context
        ) as response:
            for raw_line in response:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ProviderError("Ollama returned an invalid streaming response.") from error
                if not isinstance(event, dict):
                    raise ProviderError("Ollama returned an unexpected streaming response.")
                message = event.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content:
                        chunks.append(content)
                        on_delta(content)
                if event.get("done") is True:
                    final_response = event
                    break
    except urllib.error.HTTPError as error:
        detail = error_detail(error.read())
        suffix = f": {detail}" if detail else ""
        raise ProviderError(f"Request failed (HTTP {error.code}){suffix}") from error
    except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
        reason = getattr(error, "reason", error)
        raise ProviderError(f"Connection failed: {scrub_secrets(str(reason))[:300]}") from error
    text = "".join(chunks).strip()
    if not text:
        raise ProviderError("Ollama returned no text output.")
    return text, usage_fields(final_response or {}, "ollama")

def call_provider(
    provider: str,
    config: dict[str, Any],
    question: str,
    instructions: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, dict[str, int]]:
    if provider == "openai":
        return call_openai(config, question, instructions, max_tokens, temperature)
    if provider == "custom":
        return call_custom(config, question, instructions, max_tokens, temperature)
    if provider == "anthropic":
        return call_anthropic(config, question, instructions, max_tokens, temperature)
    if provider == "ollama":
        return call_ollama(config, question, instructions, max_tokens, temperature)
    raise CouncilError("Unknown provider.")