"""Persistence helpers for resumable plan-review sessions."""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_state_lock = threading.Lock()
_STATE_PATH = Path(__file__).resolve().parents[1] / ".model_council" / "session_state.json"


def pending_plan_path() -> Path:
    return Path(os.getenv("MC_SESSION_STATE_PATH", str(_STATE_PATH))).expanduser()


def save_paused_plan(state: dict[str, Any]) -> dict[str, Any]:
    """Persist one pending plan without provider credentials."""
    safe = {
        "plan_id": str(state.get("plan_id") or uuid.uuid4().hex),
        "status": "paused",
        "task": str(state.get("task", ""))[:14_000],
        "plan": str(state.get("plan", ""))[:6_000],
        "root": str(state.get("root", ""))[:2_000],
        "workspace_mode": str(state.get("workspace_mode", "server"))[:40],
        "agent_provider": str(state.get("agent_provider", ""))[:80],
        "max_steps": int(state.get("max_steps", 20)),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = pending_plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _state_lock:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return safe


def load_pending_plan() -> dict[str, Any] | None:
    path = pending_plan_path()
    with _state_lock:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
    return state if isinstance(state, dict) and state.get("status") in {"paused", "approved"} else None


def decide_pending_plan(plan_id: str, decision: str) -> dict[str, Any] | None:
    if decision not in {"approve", "reject", "discard"}:
        raise ValueError("Unknown pending plan decision.")
    path = pending_plan_path()
    with _state_lock:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(state, dict) or state.get("plan_id") != plan_id:
            return None
        if state.get("status") == "approved" and decision == "approve":
            return state
        if state.get("status") not in {"paused", "approved"}:
            return None
        if decision == "discard":
            path.unlink(missing_ok=True)
            return {"plan_id": plan_id, "status": "discarded"}
        if decision == "reject":
            path.unlink(missing_ok=True)
            return {"plan_id": plan_id, "status": "rejected"}
        state["status"] = "approved"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
        return state


def consume_approved_plan(plan_id: str) -> dict[str, Any] | None:
    path = pending_plan_path()
    with _state_lock:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(state, dict) or state.get("plan_id") != plan_id or state.get("status") != "approved":
            return None
        path.unlink(missing_ok=True)
        return state
