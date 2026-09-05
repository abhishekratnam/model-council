import asyncio
import json
import queue
from typing import Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.services.council import run_council_stream, synthesize_council_stream
from app.services.security import is_safe_browser_origin, scrub_secrets
from app.core.exceptions import CouncilError, ProviderError

router = APIRouter()

async def _safe_ws_send(websocket: WebSocket, payload: dict[str, Any]) -> None:
    if websocket.application_state != WebSocketState.CONNECTED:
        return
    try:
        await websocket.send_json(payload)
    except (RuntimeError, WebSocketDisconnect):
        pass

@router.websocket("/council/stream")
async def council_stream(websocket: WebSocket):
    origin = websocket.headers.get("Origin")
    if not is_safe_browser_origin(origin):
        await websocket.close(code=1008, reason="Browser origin is not allowed.")
        return

    await websocket.accept()

    browser_rpc_queue = queue.Queue()

    async def listen_for_browser_rpcs():
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                    if isinstance(msg, dict) and msg.get("rpc"):
                        browser_rpc_queue.put(msg)
                except json.JSONDecodeError:
                    pass
        except (WebSocketDisconnect, RuntimeError):
            pass

    rpc_listener = asyncio.create_task(listen_for_browser_rpcs())

    try:
        raw = await websocket.receive_text()
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise CouncilError("WebSocket request must be a JSON object.")

        action = body.get("action")
        loop = asyncio.get_running_loop()

        def emit(event: dict[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(_safe_ws_send(websocket, event))
                )
            except RuntimeError:
                pass

        if action == "ask":
            result = await asyncio.to_thread(run_council_stream, body, emit, browser_rpc_queue)
            await _safe_ws_send(websocket, {"type": "round_complete", "result": result})
        elif action == "synthesize":
            result = await asyncio.to_thread(synthesize_council_stream, body, emit, browser_rpc_queue)
            await _safe_ws_send(websocket, {"type": "synthesis_complete", "result": result})
        else:
            raise CouncilError("Unknown streaming action.")

    except WebSocketDisconnect:
        return
    except json.JSONDecodeError:
        await _safe_ws_send(websocket, {"type": "error", "message": "WebSocket request must be valid JSON."})
    except (CouncilError, ProviderError) as exc:
        await _safe_ws_send(websocket, {"type": "error", "message": scrub_secrets(str(exc))})
    except Exception:
        await _safe_ws_send(websocket, {"type": "error", "message": "Unexpected server error."})
    finally:
        rpc_listener.cancel()
        try:
            if websocket.application_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:
            pass