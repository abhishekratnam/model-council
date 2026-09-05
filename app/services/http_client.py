import json
import ssl
import socket
import urllib.error
import urllib.request
from typing import Any
from app.core.exceptions import ProviderError
from app.services.security import scrub_secrets

def error_detail(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return scrub_secrets(text.strip()[:500])
    if isinstance(body, dict):
        candidate: Any = body.get("error", body.get("message", ""))
        if isinstance(candidate, dict):
            candidate = candidate.get("message", candidate.get("type", ""))
        if isinstance(candidate, str):
            return scrub_secrets(candidate.strip()[:500])
    return ""

def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 75,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json"}
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        context = ssl.create_default_context() if url.startswith("https://") else None
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error_detail(error.read())
        suffix = f": {detail}" if detail else ""
        raise ProviderError(f"Request failed (HTTP {error.code}){suffix}") from error
    except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
        reason = getattr(error, "reason", error)
        raise ProviderError(f"Connection failed: {scrub_secrets(str(reason))[:300]}") from error
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderError("The provider returned an invalid JSON response.") from error
    if not isinstance(result, dict):
        raise ProviderError("The provider returned an unexpected response.")
    return result