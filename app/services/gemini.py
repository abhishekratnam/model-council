from typing import Any

from app.core.exceptions import ProviderError
from app.services.http_client import request_json
from app.services.validation import trim_text

URL = "https://generativelanguage.googleapis.com/v1beta/models"


def gemini_models(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = trim_text(payload.get("api_key"), field="Gemini API key", limit=500, required=True)
    response = request_json("GET", f"{URL}?pageSize=200", headers={"x-goog-api-key": api_key}, timeout=30)
    raw_models = response.get("models")
    if not isinstance(raw_models, list):
        raise ProviderError("Gemini returned an unexpected model list.")

    models: dict[str, str] = {}
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        methods = item.get("supportedGenerationMethods")
        if isinstance(methods, list) and "generateContent" not in methods:
            continue  # Skip embedding / vision-only / TTS models.
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        model_id = raw_name.strip().removeprefix("models/")
        name = item.get("displayName")
        models[model_id[:200]] = name.strip()[:160] if isinstance(name, str) and name.strip() else model_id[:200]

    ordered = [{"id": model_id, "name": name} for model_id, name in models.items()]
    ordered.sort(key=lambda model: (model["name"].casefold(), model["id"].casefold()))
    return {"models": ordered}
