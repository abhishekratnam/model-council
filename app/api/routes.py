import asyncio

from fastapi import APIRouter

from app.core.run_registry import cancel_run
from app.models.schemas import OllamaModelsPayload
from app.services.council import memory_history_response
from app.services.ollama import ollama_models
from app.services.validation import validate_session_id
from app.services import workspace
from app.core.exceptions import CouncilError
from app.core.config import DEFAULT_OLLAMA_BASE_URL, settings
from app.core.memory import memory_store

router = APIRouter()


@router.post("/council/cancel/{round_id}")
def cancel_council(round_id: str):
    return {"ok": cancel_run(round_id)}


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "ollama_default": DEFAULT_OLLAMA_BASE_URL,
        "memory": {
            "available": memory_store.available,
            "redis_url": memory_store._redact_url(memory_store.url) if memory_store.url else "",
            "ttl_seconds": memory_store.ttl,
            "max_rounds": memory_store.max_rounds,
        },
    }


@router.get("/analytics")
async def get_analytics():
    """Retrieve token usage, cost estimates, and latency metrics."""
    return await asyncio.to_thread(memory_store.get_usage_analytics)


@router.post("/ollama/models")
async def ollama_models_endpoint(payload: OllamaModelsPayload):
    body = payload.model_dump()
    return await asyncio.to_thread(ollama_models, body)


@router.get("/memory/{session_id}")
async def memory_get(session_id: str):
    sid = validate_session_id(session_id)
    if not sid:
        raise CouncilError("Invalid session ID.")
    return memory_history_response(sid)


@router.delete("/memory/{session_id}")
async def memory_clear(session_id: str):
    sid = validate_session_id(session_id)
    if not sid:
        raise CouncilError("Invalid session ID.")
    cleared = memory_store.clear_session(sid)
    return {"session_id": sid, "cleared": cleared, "available": memory_store.available}


@router.delete("/memory/{session_id}/{round_id}")
async def memory_delete_round(session_id: str, round_id: str):
    sid = validate_session_id(session_id)
    if not sid:
        raise CouncilError("Invalid session ID.")
    deleted = memory_store.delete_round(sid, round_id)
    return {"session_id": sid, "round_id": round_id, "deleted": deleted}


# ── Workspace (code agent) ───────────────────────────────────────────────────

@router.get("/workspace/roots")
async def workspace_roots_endpoint():
    """List the configured workspace roots the UI can switch between."""
    return await asyncio.to_thread(_workspace_roots_response)


def _workspace_roots_response() -> dict:
    try:
        return {"roots": workspace.workspace_roots(), "error": ""}
    except CouncilError as error:
        return {"roots": [], "error": str(error)}


@router.get("/workspace/root")
async def workspace_root_endpoint():
    """Report the default workspace root (kept for quick curl checks)."""
    return await asyncio.to_thread(_workspace_root_response)


def _workspace_root_response() -> dict:
    configured = bool(settings.MODEL_COUNCIL_WORKSPACE_ROOT.strip())
    try:
        root = workspace.workspace_root()
        return {"root": str(root), "exists": True, "configured": configured}
    except CouncilError as error:
        return {"root": "", "exists": False, "error": str(error), "configured": configured}


def _payload_root(payload: dict) -> str | None:
    root = payload.get("root")
    return root if isinstance(root, str) and root.strip() else None


@router.post("/workspace/tree")
async def workspace_tree(payload: dict):
    if not isinstance(payload, dict):
        raise CouncilError("Request body must be a JSON object.")
    base = payload.get("path", "")
    root = _payload_root(payload)
    return await asyncio.to_thread(
        workspace.list_tree, base if isinstance(base, str) else "", root)


@router.post("/workspace/read")
async def workspace_read(payload: dict):
    if not isinstance(payload, dict):
        raise CouncilError("Request body must be a JSON object.")
    path = payload.get("path")
    offset = payload.get("offset") if isinstance(payload.get("offset"), int) else 1
    limit = payload.get("limit") if isinstance(payload.get("limit"), int) else None
    return await asyncio.to_thread(
        workspace.read_file, path, offset, limit, _payload_root(payload))


@router.post("/workspace/search")
async def workspace_search(payload: dict):
    if not isinstance(payload, dict):
        raise CouncilError("Request body must be a JSON object.")
    query = payload.get("query")
    is_regex = payload.get("is_regex") is True
    return await asyncio.to_thread(
        workspace.search_workspace, query, is_regex, _payload_root(payload))
