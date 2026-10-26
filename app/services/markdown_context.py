"""Build a compact, task-focused context from already-read Markdown documents."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


DEFAULT_MARKDOWN_CONTEXT_CHARS = 18_000
_WORD_RE = re.compile(r"[a-z0-9_.+#/-]+", re.IGNORECASE)
_STOP_WORDS = {
    "about", "after", "also", "and", "any", "are", "before", "being", "can",
    "could", "does", "from", "have", "into", "more", "only", "project", "should",
    "some", "such", "task", "than", "that", "their", "them", "then", "there",
    "these", "they", "this", "those", "through", "under", "using", "what", "when",
    "where", "which", "while", "with", "would",
}
_ALWAYS_HEADINGS = {
    "shared project guidance", "discover the project", "discover project",
    "build, run, and verify", "identify the language", "plan mode and approvals",
    "tooling contracts",
}
_README_HEADINGS = {"overview", "getting started", "development", "local development", "build", "run", "test", "testing", "installation", "setup"}


@dataclass(frozen=True)
class _Section:
    source: str
    headings: tuple[str, ...]
    body: str
    order: int

    @property
    def heading(self) -> str:
        return self.headings[-1] if self.headings else "Document"

    @property
    def text(self) -> str:
        lines = [*(f"## {heading}" for heading in self.headings)]
        if self.body:
            lines.append(self.body)
        return "\n".join(lines).strip()


def _parse_sections(source: str, content: str) -> list[_Section]:
    sections: list[_Section] = []
    heading_stack: list[tuple[int, str]] = []
    current_level = 0
    current_headings: tuple[str, ...] = ()
    lines: list[str] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body or current_headings:
            sections.append(_Section(source, current_headings, body, len(sections)))

    for line in content.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if match:
            flush()
            current_level = len(match.group(1))
            title = match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= current_level:
                heading_stack.pop()
            heading_stack.append((current_level, title))
            current_headings = tuple(item[1] for item in heading_stack)
            lines = []
        else:
            lines.append(line)
    flush()
    return sections


def _terms(text: str) -> set[str]:
    return {
        word.casefold() for word in _WORD_RE.findall(text)
        if len(word) > 2 and word.casefold() not in _STOP_WORDS
    }


def _relevance(section: _Section, task_terms: set[str], category: str | None) -> int:
    heading_terms = _terms(" ".join(section.headings))
    body_terms = _terms(section.body)
    score = len(heading_terms & task_terms) * 4 + len(body_terms & task_terms)
    if category and category.casefold() in heading_terms | body_terms:
        score += 3
    if section.heading.casefold().strip("0123456789. ") in _README_HEADINGS:
        score += 2
    return score


def _is_shared_guide(section: _Section) -> bool:
    source = section.source.replace("\\", "/").casefold()
    return source.endswith("/plans/agents.md") or source == "plans/agents.md"


def _heading_contains(section: _Section, needles: set[str]) -> bool:
    normalized = " ".join(section.headings).casefold().strip("0123456789. ")
    return any(needle in normalized for needle in needles)


def _is_category_guide(section: _Section, category: str | None) -> bool:
    if not category:
        return False
    source = section.source.replace("\\", "/").casefold()
    return source.endswith(f"/plans/{category.casefold()}.md") or source == f"plans/{category.casefold()}.md"


def _is_handoff(section: _Section) -> bool:
    source = section.source.replace("\\", "/").casefold()
    return source.endswith(".model_council/plans/last_session.md") or "previous agent session log" in source


def _is_workspace_instructions(section: _Section) -> bool:
    name = section.source.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return name in {"agents.md", "claude.md", "contributing.md"} and not _is_shared_guide(section)


def read_markdown_context(
    documents: Iterable[tuple[str, str]],
    task: str,
    category: str | None,
    *,
    max_chars: int = DEFAULT_MARKDOWN_CONTEXT_CHARS,
) -> str:
    """Select relevant Markdown sections, preserving core guidance and provenance.

    `documents` are read by the caller through its existing trusted or sandboxed
    file access path. This function does no I/O, so document acquisition and
    prompt selection stay independently replaceable.
    """
    task_terms = _terms(task)
    sections: list[_Section] = []
    seen_sources: set[str] = set()
    for source, content in documents:
        normalized_source = source.replace("\\", "/")
        if normalized_source in seen_sources or not isinstance(content, str) or not content.strip():
            continue
        seen_sources.add(normalized_source)
        sections.extend(_parse_sections(normalized_source, content))

    def priority(section: _Section) -> tuple[int, int, int]:
        heading_path = " ".join(section.headings).casefold()
        if _is_shared_guide(section):
            # The language-specific subsections are supplied by the selected guide.
            if "language guides" in heading_path:
                return (1, 0, -section.order)
            if _heading_contains(section, _ALWAYS_HEADINGS):
                return (0, 0, -section.order)
            return (1, _relevance(section, task_terms, category), -section.order)
        if _is_category_guide(section, category) or _is_handoff(section) or _is_workspace_instructions(section):
            return (0, _relevance(section, task_terms, category), -section.order)
        return (2, _relevance(section, task_terms, category), -section.order)

    ordered = sorted(sections, key=priority)
    output: list[str] = []
    seen_content: set[str] = set()
    used_chars = 0
    for section in ordered:
        shared = _is_shared_guide(section)
        heading_path = " ".join(section.headings).casefold()
        if shared and "language guides" in heading_path:
            continue
        category_guide = _is_category_guide(section, category)
        handoff = _is_handoff(section)
        workspace_instructions = _is_workspace_instructions(section)
        always_keep = (
            shared and _heading_contains(section, _ALWAYS_HEADINGS)
        ) or category_guide or handoff or workspace_instructions
        score = _relevance(section, task_terms, category)
        if not always_keep and score <= 0:
            continue

        normalized_content = " ".join(section.body.casefold().split())
        if normalized_content and normalized_content in seen_content:
            continue
        rendered = f"### Source: {section.source}\n{section.text}".strip()
        extra = len(rendered) + (2 if output else 0)
        if used_chars + extra > max_chars and not always_keep:
            continue
        # Preserve required policy even if it takes the context slightly over budget.
        if normalized_content:
            seen_content.add(normalized_content)
        output.append(rendered)
        used_chars += extra

    return "\n\n".join(output)
