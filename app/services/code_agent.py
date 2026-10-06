"""The code agent: a local model drives a sandboxed agent loop over the workspace.

One JSON action per model turn (the same strict-JSON pattern as the chair),
executed against app/services/workspace.py. Writes and commands are staged and
require an explicit UI confirmation — the model never writes or executes on
its own. Cancellation reuses the council run registry.
"""
import json
import queue
import re
import time
import uuid
from typing import Any

from app.core.config import (
    CODE_AGENT_CONFIRM_TIMEOUT_SECONDS,
    CODE_AGENT_DEFAULT_MAX_STEPS,
    CODE_AGENT_HISTORY_CHAR_BUDGET,
    CODE_AGENT_MAX_STEPS_LIMIT,
    CODE_AGENT_NUM_CTX,
    CODE_AGENT_TOOL_RESULT_CHARS,
    CODE_AGENT_INSTRUCTIONS,
    MAX_PROMPT_CHARS,
)
from app.core.exceptions import CouncilError, ProviderError
from app.core.memory import memory_store
from app.core.run_registry import register_run, finish_run
from app.services import workspace
from app.services.providers import call_ollama_messages
from app.services.security import provider_config, provider_model, scrub_secrets
from app.services.validation import bounded_float, bounded_int, trim_text

VALID_ACTIONS = {"list_tree", "search", "read_file", "write_file", "edit_file", "run_command", "done", "fail"}

# _execute_action sentinels: the run must stop, not feed the text to the model.
CANCELLED, TIMED_OUT = "__cancelled__", "__confirm_timeout__"


def _parse_action(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tree_text(entries: list[dict[str, Any]]) -> str:
    lines = []
    for entry in entries:
        if entry["type"] == "dir":
            lines.append(f"{entry['path']}/")
        else:
            lines.append(f"{entry['path']} ({entry.get('size', 0):,} B)")
    return "\n".join(lines) if lines else "(empty workspace)"


def _history_chars(messages: list[dict[str, str]]) -> int:
    return sum(len(message.get("content", "")) for message in messages)


def _trim_history(messages: list[dict[str, str]]) -> None:
    """Drop the oldest action/result pairs (keeping system + task) when the
    running conversation would overflow the local model's context window."""
    trimmed = False
    while _history_chars(messages) > CODE_AGENT_HISTORY_CHAR_BUDGET and len(messages) > 4:
        del messages[2:4]
        trimmed = True
    if trimmed:
        messages.insert(2, {
            "role": "user",
            "content": "[Earlier tool results were trimmed to fit the context window. "
                       "Re-read any file you need exact contents for.]",
        })


def _wait_for_confirmation(
    emit: Any,
    rpc_queue: queue.Queue,
    cancel_event: Any,
    confirm_id: str,
    kind: str,
    detail: dict[str, Any],
) -> bool | None | str:
    """Block until the UI answers. True=approved, False=rejected,
    "timeout"=no answer, None=run cancelled."""
    emit({"type": "agent_confirm", "confirm_id": confirm_id, "kind": kind, **detail})
    deadline = time.monotonic() + CODE_AGENT_CONFIRM_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            return None
        try:
            msg = rpc_queue.get(timeout=2.0)
        except queue.Empty:
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("rpc") == "agent_confirm" and msg.get("confirm_id") == confirm_id:
            emit({"type": "agent_confirm_done", "confirm_id": confirm_id,
                  "approved": bool(msg.get("approved"))})
            return bool(msg.get("approved"))
        # Stray relay messages (e.g. ollama chunks from another tab) are ignored.
    return "timeout"


def _describe(action: str, args: dict[str, Any]) -> str:
    if action == "read_file":
        return f"Read {args.get('path', '?')}"
    if action == "search":
        return f"Search for “{str(args.get('query', ''))[:60]}”"
    if action == "list_tree":
        return "List the file tree"
    if action == "write_file":
        return f"Write {args.get('path', '?')}"
    if action == "edit_file":
        return f"Edit {args.get('path', '?')}"
    if action == "run_command":
        command = args.get("command")
        return "Run " + " ".join(command) if isinstance(command, list) else "Run command"
    if action == "done":
        return "Finish"
    if action == "fail":
        return "Give up"
    return action


def run_code_agent(payload: dict[str, Any], emit: Any, browser_rpc_queue: queue.Queue) -> dict[str, Any]:
    task = trim_text(payload.get("task"), field="Coding task", limit=MAX_PROMPT_CHARS, required=True)
    max_steps = bounded_int(payload.get("max_steps"), default=CODE_AGENT_DEFAULT_MAX_STEPS,
                            minimum=1, maximum=CODE_AGENT_MAX_STEPS_LIMIT)
    temperature = bounded_float(payload.get("temperature"), default=0.2, minimum=0, maximum=1)
    max_tokens = bounded_int(payload.get("max_tokens"), default=3_000, minimum=256, maximum=8_000)

    # Coder mode is local-only by design: on-device model, on-device files.
    config = provider_config(payload, "ollama")
    model = provider_model(config)
    if not model:
        raise CouncilError("Choose a local Ollama model for the code agent (e.g. qwen3-coder:30b).")
    root_path = workspace.resolve_root(payload.get("root"))
    root = str(root_path)

    round_id = f"code-{uuid.uuid4().hex[:12]}"
    emit({"type": "agent_start", "round_id": round_id, "root": root,
          "model": model, "max_steps": max_steps})
    cancel_event = register_run(round_id)

    started = time.perf_counter()
    steps: list[dict[str, Any]] = []
    applied_changes: list[str] = []
    commands_run: list[str] = []
    usage_totals = {"prompt_eval_count": 0, "eval_count": 0}
    cancelled = False
    ok = False
    summary = ""

    tree = workspace.list_tree(root=root)
    first_user = (
        f"WORKSPACE ROOT: {root}\n\n"
        f"TASK: {task}\n\n"
        f"CURRENT FILE TREE:\n{_tree_text(tree['entries'])}\n\n"
        "Begin. Reply with exactly one JSON action."
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": CODE_AGENT_INSTRUCTIONS},
        {"role": "user", "content": first_user},
    ]

    def _log_usage(usage: dict[str, int], elapsed_ms: int) -> None:
        usage_totals["prompt_eval_count"] += int(usage.get("prompt_eval_count") or 0)
        usage_totals["eval_count"] += int(usage.get("eval_count") or 0)
        total = usage_totals["prompt_eval_count"] + usage_totals["eval_count"]
        memory_store.log_usage("ollama", model, total, elapsed_ms)

    try:
        consecutive_parse_failures = 0
        for index in range(1, max_steps + 1):
            if cancel_event.is_set():
                cancelled = True
                summary = summary or "Stopped by user."
                break

            _trim_history(messages)
            call_started = time.perf_counter()
            raw_text, usage = call_ollama_messages(
                config, messages, max_tokens, temperature,
                lambda delta: emit({"type": "agent_delta", "delta": delta}),
                num_ctx=CODE_AGENT_NUM_CTX,
            )
            _log_usage(usage, round((time.perf_counter() - call_started) * 1_000))

            action_args = _parse_action(raw_text)
            action = str(action_args.get("action", "")).strip() if action_args else ""
            if action not in VALID_ACTIONS:
                consecutive_parse_failures += 1
                detail = "Model reply was not a valid JSON action; retrying with a reminder."
                steps.append({"index": index, "action": "invalid", "label": "Unparseable reply",
                              "status": "error", "detail": detail})
                emit({"type": "agent_step", "index": index, "label": "Unparseable reply",
                      "status": "error", "detail": detail})
                if consecutive_parse_failures >= 3:
                    summary = "Stopped: the model kept returning unparseable actions."
                    break
                messages.append({"role": "assistant", "content": raw_text})
                messages.append({"role": "user", "content": (
                    "That was not one of the required JSON actions. Reply with ONLY one JSON "
                    f"object from this list: {', '.join(sorted(VALID_ACTIONS))}."
                )})
                continue
            consecutive_parse_failures = 0

            label = _describe(action, action_args)
            emit({"type": "agent_step", "index": index, "action": action, "label": label,
                  "status": "running"})
            step_record: dict[str, Any] = {"index": index, "action": action, "label": label,
                                           "status": "complete", "detail": ""}

            if action in {"done", "fail"}:
                summary = str(action_args.get("summary", "")).strip()[:2_000]
                ok = action == "done"
                step_record["detail"] = summary
                steps.append(step_record)
                emit({"type": "agent_step", "index": index, "action": action, "label": label,
                      "status": "complete", "detail": summary})
                break

            result_text, error = _execute_action(action_args, emit, browser_rpc_queue,
                                                 cancel_event, applied_changes, commands_run,
                                                 step_record, root)
            if error == CANCELLED:
                cancelled = True
                summary = summary or "Stopped by user during a confirmation."
                steps.append(step_record)
                break
            if error == TIMED_OUT:
                summary = (f"Stopped: no confirmation arrived within "
                           f"{CODE_AGENT_CONFIRM_TIMEOUT_SECONDS}s.")
                steps.append(step_record)
                break
            if error:
                step_record["status"] = "error"
                step_record["detail"] = error
                result_text = f"The action failed: {error}. Fix the problem and try a different action."
            steps.append(step_record)
            emit({"type": "agent_step", "index": index, "action": action, "label": label,
                  "status": step_record["status"], "detail": step_record["detail"]})

            messages.append({"role": "assistant", "content": raw_text})
            messages.append({"role": "user", "content": (
                f"ACTION RESULT (step {index}, {action}):\n{result_text[:CODE_AGENT_TOOL_RESULT_CHARS]}\n\n"
                "Reply with exactly one JSON action."
            )})
        else:
            summary = summary or f"Reached the {max_steps}-step limit without a done/fail action."
    finally:
        finish_run(round_id)
        if cancelled:
            # Immediate UI feedback; the WS handler still delivers the full
            # result in a terminal agent_complete event.
            emit({"type": "agent_cancelled", "round_id": round_id, "summary": summary})

    return {
        "task": task, "round_id": round_id, "root": str(root), "model": model,
        "steps": steps, "summary": summary, "ok": ok, "cancelled": cancelled,
        "applied_changes": applied_changes, "commands_run": commands_run,
        "usage": usage_totals,
        "elapsed_ms": round((time.perf_counter() - started) * 1_000),
    }


def _execute_action(
    args: dict[str, Any],
    emit: Any,
    rpc_queue: queue.Queue,
    cancel_event: Any,
    applied_changes: list[str],
    commands_run: list[str],
    step_record: dict[str, Any],
    root: str,
) -> tuple[str, str]:
    """Run one parsed action against the run's workspace root. Returns
    (result_text_for_model, error_message). error is CANCELLED or TIMED_OUT
    when the run must stop instead."""
    action = str(args.get("action", ""))
    try:
        if action == "list_tree":
            tree = workspace.list_tree(str(args.get("path", "") or ""), root)
            step_record["detail"] = (f"{len(tree['entries'])} entries"
                                     + (" (truncated)" if tree["truncated"] else ""))
            return _tree_text(tree["entries"]), ""

        if action == "search":
            found = workspace.search_workspace(str(args.get("query", "")),
                                               args.get("is_regex") is True, root)
            step_record["detail"] = (f"{len(found['matches'])} matches"
                                     + (" (truncated)" if found["truncated"] else ""))
            lines = [f"{m['path']}:{m['line']}: {m['text']}" for m in found["matches"]]
            if found["truncated"]:
                lines.append(f"(showing first {len(found['matches'])} matches)")
            return "\n".join(lines) or "No matches.", ""

        if action == "read_file":
            offset = args.get("offset") if isinstance(args.get("offset"), int) else 1
            limit = args.get("limit") if isinstance(args.get("limit"), int) else None
            blob = workspace.read_file(str(args.get("path", "")), offset, limit, root)
            step_record["detail"] = (f"lines {blob['start_line']}–{blob['end_line']} of {blob['total_lines']}"
                                     + (" (truncated)" if blob["truncated"] else ""))
            header = f"{blob['path']} · lines {blob['start_line']}-{blob['end_line']} of {blob['total_lines']}"
            return f"{header}\n\n{blob['content']}", ""

        if action in {"write_file", "edit_file"}:
            return _staged_write_flow(action, args, emit, rpc_queue, cancel_event,
                                      applied_changes, step_record, root)

        if action == "run_command":
            argv = workspace.validate_command(args.get("command"))
            confirm_id = uuid.uuid4().hex[:12]
            decision = _wait_for_confirmation(emit, rpc_queue, cancel_event, confirm_id,
                                              "command", {"command": argv})
            if decision is None:
                return "", CANCELLED
            if decision == "timeout":
                return "", TIMED_OUT
            if not decision:
                step_record["status"] = "rejected"
                step_record["detail"] = "Command rejected by user."
                return ("The user REJECTED this command. Do not retry it unchanged; "
                        "adjust your approach or stop.", "")
            result = workspace.run_command(argv, root)
            commands_run.append(" ".join(argv))
            emit({"type": "agent_output", "command": result["command"], "stdout": result["stdout"],
                  "stderr": result["stderr"], "returncode": result["returncode"],
                  "duration_ms": result["duration_ms"], "truncated": result["truncated"]})
            step_record["detail"] = f"exit {result['returncode']} in {result['duration_ms']:,} ms" \
                + (" (timed out)" if result["timed_out"] else "")
            body = (f"exit code: {result['returncode']}\n"
                    f"--- stdout ---\n{result['stdout'] or '(empty)'}\n"
                    f"--- stderr ---\n{result['stderr'] or '(empty)'}")
            return body, ""

        raise CouncilError(f"Unknown action: {action}")
    except CouncilError as error:
        return "", scrub_secrets(str(error))
    except ProviderError as error:
        return "", scrub_secrets(str(error))


def _staged_write_flow(
    action: str,
    args: dict[str, Any],
    emit: Any,
    rpc_queue: queue.Queue,
    cancel_event: Any,
    applied_changes: list[str],
    step_record: dict[str, Any],
    root: str,
) -> tuple[str, str]:
    if action == "write_file":
        path_arg = str(args.get("path", ""))
        content = args.get("content")
        if not isinstance(content, str):
            raise CouncilError("write_file requires a string 'content'.")
        staged = workspace.stage_write(path_arg, content, root)
    else:
        path_arg = str(args.get("path", ""))
        staged = workspace.stage_edit(path_arg, args.get("find"), args.get("replace"), root)

    emit({"type": "agent_diff", "path": staged["path"], "diff": staged["diff"],
          "is_new": staged["is_new"], "action": action})
    confirm_id = uuid.uuid4().hex[:12]
    decision = _wait_for_confirmation(emit, rpc_queue, cancel_event, confirm_id,
                                      "write", {"path": staged["path"], "is_new": staged["is_new"]})
    if decision is None:
        return "", CANCELLED
    if decision == "timeout":
        return "", TIMED_OUT
    if not decision:
        step_record["status"] = "rejected"
        step_record["detail"] = f"Change to {staged['path']} rejected by user."
        return ("The user REJECTED this change. Do not propose the identical edit again; "
                "revise it or explain what you need.", "")

    if action == "write_file":
        workspace.apply_write(path_arg, content, root)
    else:
        workspace.apply_edit(path_arg, str(args.get("find")), str(args.get("replace")), root)
    applied_changes.append(staged["path"])
    step_record["detail"] = f"{'Created' if staged['is_new'] else 'Modified'} {staged['path']}"
    return (f"The change to {staged['path']} was approved and applied. "
            "Re-read the file if you need to verify exact contents."), ""
