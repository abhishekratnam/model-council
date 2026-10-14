from typing import Any

from app.core.exceptions import ProviderError
from app.services.http_client import request_json
from app.services.validation import trim_text


def openrouter_models(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = trim_text(payload.get("api_key"), field="OpenRouter API key", limit=500, required=True)
    response = request_json(
        "GET",
        "https://openrouter.ai/api/v1/models?output_modalities=text",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    raw_models = response.get("data")
    if not isinstance(raw_models, list):
        raise ProviderError("OpenRouter returned an unexpected model list.")

    models: dict[str, str] = {}
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        name = item.get("name")
        if isinstance(model_id, str) and model_id.strip():
            models[model_id.strip()[:200]] = name.strip()[:160] if isinstance(name, str) and name.strip() else model_id.strip()[:200]

    ordered = [{"id": model_id, "name": name} for model_id, name in models.items()]
    ordered.sort(key=lambda model: (model["name"].casefold(), model["id"].casefold()))
    return {"models": ordered}
