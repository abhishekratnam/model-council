from typing import Any
from app.core.exceptions import ProviderError

def extract_openai_text(response: dict[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") in {"output_text", "text"}:
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text.strip())
    if chunks:
        return "\n".join(chunks)
    raise ProviderError("OpenAI returned no text output.")

def extract_gemini_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    candidates = response.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"].strip():
                    chunks.append(part["text"].strip())
    if chunks:
        return "\n".join(chunks)
    raise ProviderError("Gemini returned no text output.")

def extract_anthropic_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    content = response.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
    if chunks:
        return "\n".join(chunks)
    raise ProviderError("Claude returned no text output.")

def usage_fields(response: dict[str, Any], provider: str) -> dict[str, int]:
    if provider == "gemini":
        metadata = response.get("usageMetadata")
        if not isinstance(metadata, dict):
            return {}
        # Normalize Gemini's camelCase counters to the OpenAI-style names the
        # analytics code already understands.
        mapping = {"promptTokenCount": "input_tokens", "candidatesTokenCount": "output_tokens",
                   "totalTokenCount": "total_tokens"}
        return {target: metadata[source] for source, target in mapping.items()
                if isinstance(metadata.get(source), int)}
    if provider in {"openai", "openrouter", "anthropic", "custom", "exo"}:
        usage = response.get("usage")
        if isinstance(usage, dict):
            return {key: value for key, value in usage.items() if isinstance(value, int)}
        return {}
    allowed = ("prompt_eval_count", "eval_count", "prompt_eval_duration", "eval_duration")
    return {key: response[key] for key in allowed if isinstance(response.get(key), int)}
