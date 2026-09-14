import asyncio
from fastapi import APIRouter
from app.models.schemas import AskPayload, SynthesizePayload, OllamaModelsPayload
from app.services.council import   _memory_history_response
from app.services.ollama import ollama_models
from app.services.validation import validate_session_id
from app.core.exceptions import CouncilError
from app.core.config import  DEFAULT_OLLAMA_BASE_URL

from app.core.memory import memory_store
router = APIRouter()

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
# In app/api/routes.py

@router.get("/analytics")
async def get_analytics():
    """Retrieve token usage, cost estimates, and latency metrics."""
    return await asyncio.to_thread(memory_store.get_usage_analytics)

# @router.post("/council/ask")
# async def council_ask(payload: AskPayload):
#     body = payload.model_dump() 
#     return await asyncio.to_thread(run_council, body)

# @router.post("/council/synthesize")
# async def council_synthesize(payload: SynthesizePayload):
#     body = payload.model_dump()
#     return await asyncio.to_thread(synthesize_council, body)

@router.post("/ollama/models")
async def ollama_models_endpoint(payload: OllamaModelsPayload):
    body = payload.model_dump()
    return await asyncio.to_thread(ollama_models, body)

@router.get("/memory/{session_id}")
async def memory_get(session_id: str):
    sid = validate_session_id(session_id)
    if not sid:
        raise CouncilError("Invalid session ID.")
    return _memory_history_response(sid)

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