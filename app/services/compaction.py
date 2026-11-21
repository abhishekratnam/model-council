"""Automatic compaction of long council conversations using the local Ollama model.

Aging rounds are merged into a rolling summary stored beside the session in
Redis, so resumed sessions keep distilled context instead of clipped fragments
(and survive the max-rounds trim). Compaction is best-effort: any failure leaves
the existing history untouched and the round unaffected.
"""

import logging
import time
from typing import Any

from app.core.config import (
    COMPACTION_INSTRUCTIONS, COMPACTION_MAX_TOKENS, COMPACTION_NUM_CTX,
    COMPACTION_TRANSCRIPT_CHAR_BUDGET, settings,
)
from app.core.memory import memory_store
from app.services.providers import call_ollama_messages
from app.services.security import provider_config, provider_model, provider_ready, scrub_secrets
from app.services.validation import truncate

logger = logging.getLogger("model_council")


def _covered_ids(summary: dict[str, Any] | None) -> set[str]:
    if not summary:
        return set()
    ids = summary.get("covered_round_ids")
    if not isinstance(ids, list):
        return set()
    return {i for i in ids if isinstance(i, str)}


def compaction_candidates(rounds: list[dict[str, Any]],
                          summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Uncovered rounds old enough to compact; the newest KEEP_ROUNDS uncovered
    rounds always stay verbatim in the context."""
    keep = max(0, settings.MODEL_COUNCIL_COMPACTION_KEEP_ROUNDS)
    covered = _covered_ids(summary)
    uncovered = [r for r in rounds if r.get("round_id") not in covered]
    if len(uncovered) <= keep:
        return []
    return uncovered[: len(uncovered) - keep]


def _render_round(round_data: dict[str, Any]) -> str:
    parts = [f"User asked: {str(round_data.get('question', ''))[:1_000]}"]
    for m in round_data.get("members", []):
        if m.get("status") == "complete":
            parts.append(f"- {m.get('label')} answered: {str(m.get('text', ''))[:700]}")
    synth = round_data.get("synthesis") or {}
    if synth.get("answer"):
        parts.append(f"Chair concluded: {str(synth.get('answer', ''))[:1_200]}")
    return "\n".join(parts)


def _build_transcript(candidates: list[dict[str, Any]],
                      summary: dict[str, Any] | None) -> str:
    parts: list[str] = []
    if summary and summary.get("summary"):
        parts.append("PREVIOUS SUMMARY:\n" + str(summary["summary"]))
    parts.append("OLDER CONVERSATION ROUNDS (oldest first):")
    parts.extend(_render_round(r) for r in candidates)
    clipped, _ = truncate("\n\n".join(parts), COMPACTION_TRANSCRIPT_CHAR_BUDGET)
    return clipped


def compact_session_memory(payload: dict[str, Any], session_id: str,
                           emit: Any = None, browser_rpc_queue: Any = None) -> dict[str, Any] | None:
    """Compact aging rounds into the rolling session summary. Never raises.

    Runs only when compaction is enabled, Redis is available, enough rounds have
    accumulated (context over the char threshold, or one round away from the
    max-rounds trim), and a local Ollama model is configured. Returns the stored
    summary record, or None when nothing was compacted.
    """
    try:
        if not settings.MODEL_COUNCIL_COMPACTION_ENABLED or not memory_store.available or not session_id:
            return None
        rounds = memory_store.load_history(session_id)
        summary = memory_store.load_summary(session_id)
        candidates = compaction_candidates(rounds, summary)
        if not candidates:
            return None
        context_chars = len(memory_store.build_context(session_id))
        trim_pressure = len(rounds) >= max(1, memory_store.max_rounds - 1)
        if context_chars < settings.MODEL_COUNCIL_COMPACTION_THRESHOLD_CHARS and not trim_pressure:
            return None

        config = provider_config(payload, "ollama")
        if provider_ready("ollama", config, require_enabled=True):
            return None  # no local summarizer configured; keep the raw history
        model = provider_model(config)
        transcript = _build_transcript(candidates, summary)
        instructions = (
            COMPACTION_INSTRUCTIONS
            + f"\nKeep the summary under {settings.MODEL_COUNCIL_COMPACTION_MAX_SUMMARY_CHARS} characters."
        )
        if emit:
            emit({"type": "compaction_start", "rounds": len(candidates)})
        started = time.perf_counter()
        text, usage = call_ollama_messages(
            config,
            [{"role": "system", "content": instructions},
             {"role": "user", "content": transcript}],
            COMPACTION_MAX_TOKENS, 0.2, lambda _delta: None,
            num_ctx=COMPACTION_NUM_CTX, format_json=False,
            emit=emit, browser_rpc_queue=browser_rpc_queue,
            delta_event_type="compaction_delta",
        )
        elapsed_ms = round((time.perf_counter() - started) * 1_000)
        text = text.strip()
        if not text:
            raise ValueError("The local model returned an empty summary.")
        text, _ = truncate(text, settings.MODEL_COUNCIL_COMPACTION_MAX_SUMMARY_CHARS)
        record = {
            "summary": text,
            "covered_round_ids": sorted(
                _covered_ids(summary)
                | {r["round_id"] for r in candidates if isinstance(r.get("round_id"), str)}
            ),
            "created_at": int(time.time()),
            "provider": "ollama",
            "model": model,
        }
        memory_store.store_summary(session_id, record)
        tokens = (usage.get("prompt_eval_count") or 0) + (usage.get("eval_count") or 0)
        memory_store.log_usage("ollama", model, tokens, elapsed_ms)
        if emit:
            emit({"type": "compaction_complete", "summary": record})
        logger.info("Compacted %d round(s) into the session summary (%d chars).",
                    len(candidates), len(text))
        return record
    except Exception as error:
        logger.warning("Memory compaction skipped: %s", scrub_secrets(str(error))[:300])
        if emit:
            emit({"type": "compaction_failed", "reason": scrub_secrets(str(error))[:200]})
        return None
