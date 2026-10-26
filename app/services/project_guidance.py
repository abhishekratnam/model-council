"""Resolve project language and load its reusable build/run guidance."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable


_GUIDES_DIR = Path(__file__).resolve().parents[2] / "plans"
_SUPPORTED = ("python", "rust", "golang", "javascript")

_FILE_SIGNALS = {
    "python": {"pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "pipfile", "poetry.lock", "uv.lock"},
    "rust": {"cargo.toml", "cargo.lock"},
    "golang": {"go.mod", "go.work"},
    "javascript": {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"},
}
_EXTENSION_SIGNALS = {
    "python": {".py"},
    "rust": {".rs"},
    "golang": {".go"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"},
}
_TASK_TERMS = {
    "python": (r"\bpython(?:3)?\b", r"\b(?:pip|poetry|uv|pytest)\b", r"\.py\b"),
    "rust": (r"\brust\b", r"\bcargo\b", r"\.rs\b"),
    "golang": (r"\bgo(lang)?\b", r"\bgofmt\b", r"\bgo test\b", r"\.go\b"),
    "javascript": (r"\bjavascript\b", r"\btypescript\b", r"\b(?:node|npm|pnpm|yarn|bun|vite|next(?:\.js)?)\b", r"\.(?:js|jsx|mjs|cjs|ts|tsx)\b"),
}


@dataclass(frozen=True)
class ProjectGuidance:
    category: str | None
    guidance: str
    candidates: tuple[str, ...] = ()
    documents: tuple[tuple[str, str], ...] = ()

    @property
    def ambiguous(self) -> bool:
        return self.category is None and bool(self.candidates)


def _entry_paths(entries: Iterable[dict[str, Any]] | Iterable[str]) -> list[str]:
    paths: list[str] = []
    for entry in entries:
        value = entry if isinstance(entry, str) else entry.get("path", "")
        if isinstance(value, str) and value:
            paths.append(value.replace("\\", "/"))
    return paths


def _task_matches(task: str) -> set[str]:
    return {
        category for category, patterns in _TASK_TERMS.items()
        if any(re.search(pattern, task, flags=re.IGNORECASE) for pattern in patterns)
    }


def _load_guide(category: str) -> str:
    path = _GUIDES_DIR / f"{category}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_guidance_documents(
    category: str | None,
    existing: tuple[tuple[str, str], ...] = (),
) -> tuple[tuple[str, str], ...]:
    """Read shared guidance once and append the selected language guide once."""
    documents = list(existing)
    sources = {source.casefold() for source, _ in documents}
    if "plans/agents.md" not in sources:
        shared = _load_guide("agents")
        if shared:
            documents.append(("plans/agents.md", shared))
    if category and f"plans/{category}.md" not in sources:
        specific = _load_guide(category)
        if specific:
            documents.append((f"plans/{category}.md", specific))
    return tuple(documents)


def _guidance_text(documents: tuple[tuple[str, str], ...]) -> str:
    return "\n\n".join(content for _, content in documents)


def resolve_project_guidance(
    entries: Iterable[dict[str, Any]] | Iterable[str], task: str,
    category_hint: str | None = None,
    existing_documents: tuple[tuple[str, str], ...] = (),
) -> ProjectGuidance:
    """Choose a supported category from workspace signals and the task target."""
    paths = _entry_paths(entries)
    detected: set[str] = set()
    for path in paths:
        name = Path(path).name.casefold()
        suffix = Path(name).suffix
        for category in _SUPPORTED:
            if name in _FILE_SIGNALS[category] or suffix in _EXTENSION_SIGNALS[category]:
                detected.add(category)

    if not detected:
        documents = _load_guidance_documents(None, existing_documents)
        return ProjectGuidance(None, "", (), documents)
    if category_hint:
        hinted = category_hint.strip().casefold()
        if hinted in detected:
            documents = _load_guidance_documents(hinted, existing_documents)
            return ProjectGuidance(hinted, _guidance_text(documents), tuple(sorted(detected)), documents)
    if len(detected) == 1:
        category = next(iter(detected))
        documents = _load_guidance_documents(category, existing_documents)
        return ProjectGuidance(category, _guidance_text(documents), (category,), documents)

    task_matches = _task_matches(task) & detected
    if len(task_matches) == 1:
        category = next(iter(task_matches))
        documents = _load_guidance_documents(category, existing_documents)
        return ProjectGuidance(category, _guidance_text(documents), tuple(sorted(detected)), documents)
    documents = _load_guidance_documents(None, existing_documents)
    return ProjectGuidance(None, _guidance_text(documents), tuple(sorted(detected)), documents)


def approved_category_hint(plan: str) -> str | None:
    """Read an explicit category choice from the user's edited plan."""
    match = re.search(
        r"^\s*project\s+category\s*:\s*(python|rust|golang|javascript)\s*$",
        plan,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return match.group(1).casefold() if match else None
