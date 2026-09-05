import os
import re
import ipaddress
import urllib.parse
from typing import Any
from app.core.exceptions import CouncilError
from app.core.config import settings, DEFAULT_OLLAMA_BASE_URL, PROVIDER_LABELS
from app.services.validation import trim_text

def scrub_secrets(value: str) -> str:
    patterns = (
        r"sk-ant-[A-Za-z0-9_\-]{8,}",
        r"sk-[A-Za-z0-9_\-]{8,}",
        r"Bearer\s+[A-Za-z0-9_\-\.]{8,}",
        r"x-api-key[=:]\s*[A-Za-z0-9_\-\.]{8,}",
    )
    cleaned = value
    for pattern in patterns:
        cleaned = re.sub(pattern, "[redacted]", cleaned, flags=re.IGNORECASE)
    return cleaned

def is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    if hostname == "0.0.0.0":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False

def normalized_origin(value: str) -> str | None:
    parsed = urllib.parse.urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), "", "", ""))

def configured_allowed_origins() -> set[str]:
    raw = settings.MODEL_COUNCIL_ALLOWED_ORIGINS.strip()
    if not raw:
        return set()
    if raw == "*":
        return {"*"}
    return {origin for item in raw.split(",") if (origin := normalized_origin(item))}

def is_safe_browser_origin(origin: str | None) -> bool:
    if not origin:
        return True
    normalized = normalized_origin(origin)
    if not normalized:
        return False
    configured = configured_allowed_origins()
    if "*" in configured:
        return True
    if configured:
        return normalized in configured
    parsed = urllib.parse.urlsplit(normalized)
    return parsed.scheme == "http" and is_loopback_host(parsed.hostname)

def clean_ollama_base_url(value: Any) -> str:
    raw = trim_text(
        value if value is not None else DEFAULT_OLLAMA_BASE_URL,
        field="Ollama URL",
        limit=300,
        required=True,
    )
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CouncilError("Ollama URL must start with http:// or https://.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CouncilError("Ollama URL cannot include credentials, a query, or a fragment.")
    if parsed.path.rstrip("/") not in {"", "/api"}:
        raise CouncilError("Use the Ollama server address, not a specific API endpoint.")
        
    # Use settings instead of os.environ
    allow_remote = settings.MODEL_COUNCIL_ALLOW_REMOTE_OLLAMA
    if not allow_remote and not is_loopback_host(parsed.hostname):
        raise CouncilError(
            "Ollama URL must use localhost or a loopback address. "
            "Set MODEL_COUNCIL_ALLOW_REMOTE_OLLAMA=1 only if you intentionally need a remote server."
        )
    path = "" if parsed.path.rstrip("/") == "/api" else parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

def provider_config(payload: dict[str, Any], provider: str) -> dict[str, Any]:
    providers = payload.get("providers", {})
    if not isinstance(providers, dict):
        raise CouncilError("Provider settings must be an object.")
    config = providers.get(provider, {})
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise CouncilError(f"{PROVIDER_LABELS[provider]} settings must be an object.")
    return config

def provider_model(config: dict[str, Any]) -> str:
    model = config.get("model", "")
    if not isinstance(model, str):
        return ""
    return model.strip()[:200]

def provider_label(provider: str, config: dict[str, Any]) -> str:
    if provider != "custom":
        return PROVIDER_LABELS[provider]
    label = config.get("label", "")
    if isinstance(label, str) and label.strip():
        return label.strip()[:80]
    return PROVIDER_LABELS[provider]

def provider_enabled(config: dict[str, Any]) -> bool:
    return config.get("enabled", True) is not False

def clean_custom_endpoint(config: dict[str, Any]) -> str:
    raw = trim_text(config.get("endpoint"), field="Custom endpoint", limit=600, required=True)
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CouncilError("Custom endpoint must start with http:// or https://.")
    if parsed.username or parsed.password or parsed.fragment:
        raise CouncilError("Custom endpoint cannot include credentials or a fragment.")
    mode = config.get("mode", "responses")
    if mode not in {"azure", "responses"}:
        raise CouncilError("Custom provider mode must be Azure or Responses API.")
    path = parsed.path.rstrip("/")
    if mode == "azure":
        if path.endswith("/responses"):
            normalized_path = path
        elif path.endswith("/openai"):
            normalized_path = f"{path}/responses"
        elif path in {"", "/"}:
            normalized_path = "/openai/responses"
        else:
            raise CouncilError("Azure endpoint must be the resource URL or end with /openai.")
    else:
        if not path.endswith("/responses"):
            raise CouncilError("Responses API endpoint must end with /responses.")
        normalized_path = path
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, normalized_path, parsed.query, ""))

def custom_string_map(value: Any, *, field: str, limit: int = 20) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > limit:
        raise CouncilError(f"{field} must be an object with at most {limit} entries.")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 120:
            raise CouncilError(f"{field} has an invalid name.")
        if not isinstance(item, (str, int, float, bool)):
            raise CouncilError(f"{field} values must be text, numbers, or booleans.")
        text = str(item).strip()
        if len(text) > 1_000:
            raise CouncilError(f"{field} values must be 1,000 characters or fewer.")
        result[key.strip()] = text
    return result

def custom_response_url(config: dict[str, Any]) -> str:
    endpoint = clean_custom_endpoint(config)
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(endpoint).query, keep_blank_values=True))
    query.update(custom_string_map(config.get("query_params"), field="Custom query parameters"))
    parsed = urllib.parse.urlsplit(endpoint)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))

def provider_ready(provider: str, config: dict[str, Any], *, require_enabled: bool) -> str | None:
    if require_enabled and not provider_enabled(config):
        return "Disabled"
    if not provider_model(config):
        return "Choose a model"
    if provider in {"openai", "anthropic"}:
        key = config.get("api_key", "")
        if not isinstance(key, str) or not key.strip():
            return "No API key supplied"
    if provider == "custom":
        try:
            clean_custom_endpoint(config)
            custom_string_map(config.get("headers"), field="Custom headers")
            custom_string_map(config.get("query_params"), field="Custom query parameters")
        except CouncilError as error:
            return str(error)
        auth_type = config.get("auth_type", "bearer")
        if auth_type not in {"bearer", "api-key", "none"}:
            return "Custom authentication must be Bearer, api-key, or none"
        if auth_type != "none":
            key = config.get("api_key", "")
            if not isinstance(key, str) or not key.strip():
                return "No API key supplied"
    if provider == "ollama":
        try:
            clean_ollama_base_url(config.get("base_url"))
        except CouncilError as error:
            return str(error)
    return None