"""OpenRouter chat client with bounded empty-response retries and model fallback."""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any

from app.core.exceptions import ProviderError

logger = logging.getLogger(__name__)
URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_FALLBACK_MODELS = ("openrouter/auto",)


def _retry_after(headers: Any) -> float | None:
    value = headers.get("Retry-After") if headers else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _request(payload: dict[str, Any], api_key: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw.decode("utf-8", errors="replace"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        error = body.get("error") if isinstance(body, dict) else None
        logger.error("OpenRouter raw JSON: %s", body)
        logger.error("OpenRouter data.error: %s", error)
        exc.raw_json = body
        raise
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("OpenRouter returned invalid JSON.") from exc
    if not isinstance(body, dict):
        raise ProviderError("OpenRouter returned an unexpected response.")
    logger.info("OpenRouter raw JSON: %s", body)
    error = body.get("error")
    if error:
        logger.error("OpenRouter data.error: %s", error)
    data = body.get("data")
    if isinstance(data, dict) and data.get("error"):
        logger.error("OpenRouter data.error: %s", data["error"])
    return body


def _text(response: dict[str, Any]) -> tuple[str, str | None]:
    choices = response.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "\n".join(
            block["text"].strip()
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str) and block["text"].strip()
        )
    else:
        text = ""
    finish_reason = choice.get("finish_reason")
    logger.info("OpenRouter finish_reason: %s", finish_reason)
    return text, finish_reason if isinstance(finish_reason, str) else None


def chat_completion(
    *, config: dict[str, Any], messages: list[dict[str, str]], max_tokens: int,
    temperature: float, timeout: int = 75,
) -> tuple[str, dict[str, Any]]:
    api_key = str(config.get("api_key") or os.getenv("OPENROUTER_API_KEY", "")).strip()
    if not api_key:
        raise ProviderError("OpenRouter API key is missing.")
    primary = str(config.get("model") or config.get("model_id") or "openrouter/auto").strip()
    configured = config.get("fallback_models") or os.getenv("OPENROUTER_FALLBACK_MODELS", "")
    if isinstance(configured, str):
        fallback_models = [item.strip() for item in configured.split(",") if item.strip()]
    else:
        fallback_models = [str(item).strip() for item in configured if str(item).strip()]
    if not fallback_models:
        fallback_models = list(DEFAULT_FALLBACK_MODELS)
    models = list(dict.fromkeys([primary, *fallback_models]))
    last_error: Exception | None = None

    for model in models:
        retry_after_delay: float | None = None
        for attempt, delay in enumerate((0, 1, 2, 4)):
            wait = retry_after_delay if retry_after_delay is not None else delay
            retry_after_delay = None
            if wait:
                time.sleep(wait)
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max(2048, int(max_tokens)),
                "temperature": temperature,
            }
            try:
                response = _request(payload, api_key, timeout)
            except urllib.error.HTTPError as exc:
                retry_after = _retry_after(exc.headers)
                if retry_after is not None and attempt < 3:
                    retry_after_delay = retry_after
                    continue
                last_error = ProviderError(f"OpenRouter request failed (HTTP {exc.code}).")
                break
            error = response.get("error")
            if error:
                last_error = ProviderError(f"OpenRouter error: {error}")
                break
            text, _ = _text(response)
            if text:
                return text, response
            last_error = ProviderError("OpenRouter returned no text output.")
    if last_error:
        raise last_error
    raise ProviderError("OpenRouter returned no text output.")
