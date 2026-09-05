from typing import Any
from app.core.exceptions import ProviderError
from app.services.http_client import request_json
from app.services.security import clean_ollama_base_url

def ollama_models(payload: dict[str, Any]) -> dict[str, Any]:
    base_url = clean_ollama_base_url(payload.get("base_url"))
    response = request_json("GET", f"{base_url}/api/tags", timeout=12)
    raw_models = response.get("models")
    if not isinstance(raw_models, list):
        raise ProviderError("Ollama returned an unexpected model list.")
    models: list[dict[str, str]] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            models.append({"name": name.strip(), "details": str(item.get("details", ""))[:200]})
    return {"base_url": base_url, "models": models}