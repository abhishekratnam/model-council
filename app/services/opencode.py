from typing import Any

from app.core.exceptions import ProviderError
from app.services.http_client import request_json
from app.services.validation import trim_text


def opencode_models(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = trim_text(payload.get("api_key"), field="OpenCode API key", limit=500, required=True)
    response = request_json(
        "GET",
        "https://opencode.ai/inference/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    raw_models = response.get("data")
    if not isinstance(raw_models, list):
        raise ProviderError("OpenCode returned an unexpected model list.")

    models: dict[str, dict[str, str]] = {}
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        name = item.get("name")
        display = name.strip()[:160] if isinstance(name, str) and name.strip() else model_id.strip()[:200]
        # The model's `api` object is keyed by protocol: chat-completions, responses,
        # messages (Anthropic) or generate-content (Gemini). The council consumes the
        # OpenAI-compatible gateway, so only the OpenAI families are usable here.
        api = item.get("api")
        families = set(api.keys()) if isinstance(api, dict) else set()
        protocol = ""
        if "responses" in families:
            protocol = "responses"
        elif "chat-completions" in families:
            protocol = "chat-completions"
        models[model_id.strip()[:200]] = {"id": model_id.strip()[:200], "name": display, "protocol": protocol}

    ordered = list(models.values())
    ordered.sort(key=lambda model: (model["name"].casefold(), model["id"].casefold()))
    return {"models": ordered}
