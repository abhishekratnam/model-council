from typing import Any

from app.core.config import DEFAULT_EXO_BASE_URL
from app.core.exceptions import ProviderError
from app.services.http_client import request_json
from app.services.security import clean_exo_base_url


def _active_model_ids(state: dict[str, Any]) -> list[str]:
    """Read model IDs from exo's active instance records across state shapes."""
    instances = state.get("instances", {})
    found: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"modelId", "model_id"} and isinstance(item, str) and item.strip():
                    found.append(item.strip())
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(instances)
    return list(dict.fromkeys(found))


def exo_models(payload: dict[str, Any]) -> dict[str, Any]:
    base_url = clean_exo_base_url(payload.get("base_url", DEFAULT_EXO_BASE_URL))
    response = request_json("GET", f"{base_url}/v1/models", timeout=12)
    raw_models = response.get("data", response.get("models", [])) if isinstance(response, dict) else response
    if not isinstance(raw_models, list):
        raise ProviderError("exo returned an unexpected model list.")

    # The model catalog can expose a short name while the active instance uses
    # its canonical ID (for example, "gemma-..." vs "mlx-community/gemma-...").
    # Read state so the selector can use canonical IDs and avoid unloaded models.
    try:
        state = request_json("GET", f"{base_url}/state", timeout=12)
        active_ids = _active_model_ids(state)
    except ProviderError:
        active_ids = []
    catalog_by_suffix: dict[str, list[dict[str, str]]] = {}
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        name = item.get("id") or item.get("name")
        if isinstance(name, str) and name.strip():
            name = name.strip()
            catalog_by_suffix.setdefault(name.rsplit("/", 1)[-1], []).append({
                "name": name,
                "details": str(item.get("owned_by", ""))[:200],
            })

    if active_ids:
        # Only offer models that exo currently has an instance for. The catalog
        # also includes models that are available but not loaded, which fail
        # chat requests with "No instance found".
        models = []
        for model_id in active_ids:
            catalog_matches = catalog_by_suffix.get(model_id.rsplit("/", 1)[-1], [])
            details = catalog_matches[0]["details"] if len(catalog_matches) == 1 else "Active exo instance"
            models.append({"name": model_id, "details": details})
    else:
        models = [model for entries in catalog_by_suffix.values() for model in entries]
    return {"base_url": base_url, "models": models}
