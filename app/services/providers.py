import json
import ssl
import socket
import os
import queue
import urllib.parse
import urllib.error
import urllib.request
import uuid
from typing import Any
from app.core.config import DEFAULT_OLLAMA_BASE_URL, OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS
from app.core.exceptions import CouncilError, ProviderError
from app.services.http_client import request_json, error_detail
from app.services.extractors import extract_openai_text, extract_anthropic_text, extract_gemini_text, usage_fields
from app.services.security import clean_ollama_base_url, clean_exo_base_url, is_loopback_host, provider_model, custom_string_map, custom_response_url, scrub_secrets
from app.llm.openrouter_client import chat_completion


def exo_relay_messages(config: dict[str, Any], messages: list[dict[str, str]], max_tokens: int, temperature: float,
                       emit: Any, browser_rpc_queue: queue.Queue, delta_event_type: str, provider: str = "exo") -> tuple[str, dict[str, int]]:
    request_id = uuid.uuid4().hex
    emit({"type": "rpc_exo_chat", "request_id": request_id, "model": provider_model(config), "messages": messages,
          "max_tokens": max_tokens, "temperature": temperature})
    chunks: list[str] = []
    usage: dict[str, int] = {}
    while True:
        try:
            msg = (browser_rpc_queue.get_for(request_id, OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS)
                   if hasattr(browser_rpc_queue, "get_for") else browser_rpc_queue.get(timeout=OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS))
        except queue.Empty:
            raise ProviderError("Browser took too long to respond from exo.")
        if msg.get("request_id") != request_id:
            continue
        if msg.get("rpc") == "exo_chunk":
            content = msg.get("content", "")
            if content:
                chunks.append(content)
                if delta_event_type == "member_delta":
                    emit({"type": delta_event_type, "provider": provider, "delta": content})
                else:
                    emit({"type": delta_event_type, "delta": content})
        elif msg.get("rpc") == "exo_done":
            usage = msg.get("usage", {})
            break
        elif msg.get("rpc") == "exo_error":
            raise ProviderError(msg.get("error", "Browser failed to reach exo."))
    text = "".join(chunks).strip()
    if not text:
        raise ProviderError("exo returned no text output.")
    return text, usage_fields({"usage": usage}, "exo")


def _stream_exo_chat(config: dict[str, Any], messages: list[dict[str, str]], max_tokens: int,
                     temperature: float, on_delta: Any) -> tuple[str, dict[str, int]]:
    base_url = clean_exo_base_url(config.get("base_url"))
    request = urllib.request.Request(f"{base_url}/v1/chat/completions",
        data=json.dumps({"model": provider_model(config), "messages": messages, "stream": True,
                         "max_tokens": max_tokens, "temperature": temperature,
                         "stream_options": {"include_usage": True}}, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "text/event-stream", "Content-Type": "application/json"}, method="POST")
    chunks: list[str] = []
    usage: dict[str, Any] = {}
    try:
        context = ssl.create_default_context() if base_url.startswith("https://") else None
        with urllib.request.urlopen(request, timeout=OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS, context=context) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError as error:
                    raise ProviderError("exo returned an invalid streaming response.") from error
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                choices = event.get("choices") or []
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content") if isinstance(delta, dict) else None
                    if isinstance(content, str) and content:
                        chunks.append(content)
                        on_delta(content)
    except urllib.error.HTTPError as error:
        detail = error_detail(error.read())
        raise ProviderError(f"Request failed (HTTP {error.code}){': ' + detail if detail else ''}") from error
    except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
        raise ProviderError(f"Connection failed: {scrub_secrets(str(getattr(error, 'reason', error)))[:300]}") from error
    text = "".join(chunks).strip()
    if not text:
        raise ProviderError("exo returned no text output.")
    return text, usage_fields({"usage": usage}, "exo")


def call_exo_messages(config: dict[str, Any], messages: list[dict[str, str]], max_tokens: int, temperature: float,
                      on_delta: Any, *, emit: Any = None, browser_rpc_queue: queue.Queue | None = None,
                      delta_event_type: str = "agent_delta") -> tuple[str, dict[str, int]]:
    base_url = clean_exo_base_url(config.get("base_url"))
    if emit is not None and browser_rpc_queue is not None and is_loopback_host(urllib.parse.urlsplit(base_url).hostname):
        return exo_relay_messages(config, messages, max_tokens, temperature, emit, browser_rpc_queue, delta_event_type)
    return _stream_exo_chat(config, messages, max_tokens, temperature, on_delta)

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

GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

def _gemini_api_key(config: dict[str, Any]) -> str:
    key = str(config.get("api_key", "")).strip()
    if not key:
        key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ProviderError("No Gemini API key supplied.")
    return key

def _gemini_generation_config(max_tokens: int, temperature: float) -> dict[str, Any]:
    return {"temperature": temperature, "maxOutputTokens": max_tokens}

def _gemini_generate(config: dict[str, Any], messages: list[dict[str, str]], max_tokens: int,
                     temperature: float) -> dict[str, Any]:
    """Shared Gemini generateContent request. System/developer turns become the
    system instruction; contents only carry 'user'/'model' roles."""
    system_text = "\n\n".join(
        message["content"] for message in messages
        if message.get("role") in {"system", "developer"}
    )
    contents = [
        {"role": "model" if message.get("role") == "assistant" else "user", "parts": [{"text": message["content"]}]}
        for message in messages if message.get("role") in {"user", "assistant"}
    ]
    payload: dict[str, Any] = {"contents": contents,
                               "generationConfig": _gemini_generation_config(max_tokens, temperature)}
    if system_text:
        payload["system_instruction"] = {"parts": [{"text": system_text}]}
    return request_json(
        "POST",
        f"{GEMINI_API_BASE_URL}/{urllib.parse.quote(provider_model(config), safe='')}@generateContent",
        headers={"x-goog-api-key": _gemini_api_key(config)},
        payload=payload,
    )

def call_gemini(config: dict[str, Any], question: str, instructions: str, max_tokens: int, temperature: float) -> tuple[str, dict[str, int]]:
    response = _gemini_generate(
        config,
        [{"role": "system", "content": instructions}, {"role": "user", "content": question}],
        max_tokens, temperature,
    )
    return extract_gemini_text(response), usage_fields(response, "gemini")

def call_openrouter(config: dict[str, Any], question: str, instructions: str, max_tokens: int, temperature: float) -> tuple[str, dict[str, int]]:
    text, response = chat_completion(
        config=config,
        messages=[{"role": "system", "content": instructions}, {"role": "user", "content": question}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return text, usage_fields(response, "openrouter")

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
    return ollama_relay_messages(
        config,
        [{"role": "system", "content": instructions}, {"role": "user", "content": question}],
        {"temperature": temperature, "num_predict": max_tokens},
        emit,
        browser_rpc_queue,
        delta_event_type,
        provider,
    )

def ollama_relay_messages(
    config: dict[str, Any],
    messages: list[dict[str, str]],
    options: dict[str, Any],
    emit: Any,
    browser_rpc_queue: queue.Queue,
    delta_event_type: str = "agent_delta",
    provider: str = "ollama",
    *,
    keep_alive: str = "5m",
    format_json: bool = False,
    format_schema: dict[str, Any] | None = None,
) -> tuple[str, dict[str, int]]:
    request_id = uuid.uuid4().hex
    rpc = {
        "type": "rpc_ollama_chat",
        "request_id": request_id,
        "model": provider_model(config),
        "messages": messages,
        "options": options,
        "keep_alive": keep_alive,
    }
    if format_schema is not None:
        rpc["format"] = format_schema
    elif format_json:
        rpc["format"] = "json"
    emit(rpc)
    
    chunks: list[str] = []
    final_usage: dict[str, int] = {}
    while True:
        try:
            msg = (browser_rpc_queue.get_for(request_id, OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS)
                   if hasattr(browser_rpc_queue, "get_for") else browser_rpc_queue.get(timeout=OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS))
        except queue.Empty:
            raise ProviderError("Browser took too long to respond from local Ollama.")
        if msg.get("request_id") != request_id:
            continue
            
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

def _stream_ollama_chat(base_url: str, payload: dict[str, Any], on_delta: Any) -> tuple[str, dict[str, int]]:
    """POST /api/chat with NDJSON streaming; shared by single-turn and agent calls."""
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
    return _stream_ollama_chat(base_url, payload, on_delta)

def call_ollama_messages(
    config: dict[str, Any],
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    on_delta: Any,
    *,
    num_ctx: int,
    format_json: bool = True,
    format_schema: dict[str, Any] | None = None,
    emit: Any = None,
    browser_rpc_queue: queue.Queue | None = None,
    delta_event_type: str = "agent_delta",
) -> tuple[str, dict[str, int]]:
    """Multi-turn agent call. Structured JSON output (schema when given, else
    generic JSON mode) + an explicit context window — Ollama's default num_ctx
    silently truncates file contents otherwise."""
    base_url = clean_ollama_base_url(config.get("base_url"))
    payload: dict[str, Any] = {
        "model": provider_model(config),
        "stream": True,
        "think": False,
        "messages": messages,
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": num_ctx},
        "keep_alive": "15m",
    }
    if format_schema is not None:
        payload["format"] = format_schema
    elif format_json:
        payload["format"] = "json"
    if emit is not None and browser_rpc_queue is not None:
        hostname = urllib.parse.urlsplit(base_url).hostname
        if is_loopback_host(hostname):
            return ollama_relay_messages(
                config,
                messages,
                payload["options"],
                emit,
                browser_rpc_queue,
                delta_event_type,
                keep_alive=payload["keep_alive"],
                format_json=format_json,
                format_schema=format_schema,
            )
    return _stream_ollama_chat(base_url, payload, on_delta)

def call_agent_messages(
    provider: str,
    config: dict[str, Any],
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    on_delta: Any,
    *,
    num_ctx: int,
    emit: Any = None,
    browser_rpc_queue: queue.Queue | None = None,
    delta_event_type: str = "agent_delta",
) -> tuple[str, dict[str, int]]:
    """Run one complete agent turn with its selected provider."""
    if provider == "ollama":
        return call_ollama_messages(
            config, messages, max_tokens, temperature, on_delta,
            num_ctx=num_ctx, emit=emit, browser_rpc_queue=browser_rpc_queue,
            delta_event_type=delta_event_type,
        )
    if provider == "exo":
        return call_exo_messages(config, messages, max_tokens, temperature, on_delta,
            emit=emit, browser_rpc_queue=browser_rpc_queue, delta_event_type=delta_event_type)

    if provider in {"openai", "custom"}:
        if provider == "openai":
            url = "https://api.openai.com/v1/responses"
            headers = {"Authorization": f"Bearer {str(config.get('api_key', '')).strip()}"}
        else:
            headers = custom_string_map(config.get("headers"), field="Custom headers")
            auth_type = config.get("auth_type", "bearer")
            api_key = str(config.get("api_key", "")).strip()
            if auth_type == "bearer":
                headers["Authorization"] = f"Bearer {api_key}"
            elif auth_type == "api-key":
                headers["api-key"] = api_key
            url = custom_response_url(config)
        response = request_json(
            "POST", url, headers=headers,
            payload={
                "model": provider_model(config),
                "input": messages,
                "max_output_tokens": max_tokens,
                "temperature": temperature,
                "store": False,
            },
        )
        text = extract_openai_text(response)
        usage = usage_fields(response, provider)
    elif provider == "openrouter":
        text, response = chat_completion(
            config=config,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        usage = usage_fields(response, provider)
    elif provider == "gemini":
        response = _gemini_generate(config, messages, max_tokens, temperature)
        text = extract_gemini_text(response)
        usage = usage_fields(response, provider)
    elif provider == "anthropic":
        system_text = "\n\n".join(
            message["content"] for message in messages
            if message.get("role") in {"system", "developer"}
        )
        conversation = [
            {"role": message["role"], "content": message["content"]}
            for message in messages if message.get("role") in {"user", "assistant"}
        ]
        response = request_json(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": str(config.get("api_key", "")).strip(),
                "anthropic-version": "2023-06-01",
            },
            payload={
                "model": provider_model(config),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_text,
                "messages": conversation,
            },
        )
        text = extract_anthropic_text(response)
        usage = usage_fields(response, provider)
    else:
        raise CouncilError("Unsupported coding agent provider.")

    on_delta(text)
    return text, usage

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
    if provider == "openrouter":
        return call_openrouter(config, question, instructions, max_tokens, temperature)
    if provider == "custom":
        return call_custom(config, question, instructions, max_tokens, temperature)
    if provider == "anthropic":
        return call_anthropic(config, question, instructions, max_tokens, temperature)
    if provider == "gemini":
        return call_gemini(config, question, instructions, max_tokens, temperature)
    if provider == "ollama":
        # Ollama has no non-streaming path left: aggregate the stream silently.
        return call_ollama_stream(config, question, instructions, max_tokens, temperature,
                                  lambda _delta: None)
    if provider == "exo":
        return call_exo_messages(config,
            [{"role": "system", "content": instructions}, {"role": "user", "content": question}],
            max_tokens, temperature, lambda _delta: None)
    raise CouncilError("Unknown provider.")
