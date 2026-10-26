from app.services import project_guidance
from app.services.project_guidance import approved_category_hint, resolve_project_guidance


def test_resolves_each_supported_language_from_project_files() -> None:
    examples = {
        "python": ["pyproject.toml", "app/main.py"],
        "rust": ["Cargo.toml", "src/main.rs"],
        "golang": ["go.mod", "cmd/server/main.go"],
        "javascript": ["package.json", "src/app.tsx"],
    }
    guide_titles = {
        "python": "# Python project guidance",
        "rust": "# Rust project guidance",
        "golang": "# Go project guidance",
        "javascript": "# JavaScript and TypeScript project guidance",
    }

    for category, entries in examples.items():
        result = resolve_project_guidance(entries, "Inspect this project")
        assert result.category == category
        assert result.guidance
        assert result.ambiguous is False
        assert result.guidance.index("Shared project guidance") < result.guidance.index(
            guide_titles[category]
        )


def test_task_selects_target_in_mixed_workspace() -> None:
    entries = ["Cargo.toml", "src/lib.rs", "package.json", "web/app.tsx"]

    result = resolve_project_guidance(entries, "Fix the Rust cargo test failure")

    assert result.category == "rust"
    assert set(result.candidates) == {"rust", "javascript"}
    assert "Cargo.toml" in result.guidance


def test_ambiguous_mixed_workspace_requires_explicit_category() -> None:
    result = resolve_project_guidance(
        ["pyproject.toml", "main.py", "go.mod", "cmd/api/main.go"],
        "Improve the service",
    )

    assert result.category is None
    assert result.ambiguous is True
    assert result.candidates == ("golang", "python")


def test_approved_plan_can_choose_a_detected_category() -> None:
    entries = ["Cargo.toml", "src/main.rs", "package.json", "src/index.ts"]
    hint = approved_category_hint("## Clarification\nProject category: javascript\n")

    result = resolve_project_guidance(entries, "Update the application", category_hint=hint)

    assert result.category == "javascript"
    assert "package.json" in result.guidance


def test_late_category_selection_reuses_already_loaded_shared_guide(monkeypatch) -> None:
    reads: list[str] = []

    def fake_load_guide(category: str) -> str:
        reads.append(category)
        return f"# {category} guide"

    monkeypatch.setattr(project_guidance, "_load_guide", fake_load_guide)
    shared = ("plans/agents.md", "# Shared guidance")

    result = resolve_project_guidance(
        ["Cargo.toml", "package.json"],
        "Improve the project",
        category_hint="rust",
        existing_documents=(shared,),
    )

    assert reads == ["rust"]
    assert result.documents[0] == shared
    assert result.documents[1] == ("plans/rust.md", "# rust guide")


def test_unknown_workspace_does_not_guess_a_category() -> None:
    result = resolve_project_guidance(["README.md", "Makefile"], "Run this project")

    assert result.category is None
    assert result.ambiguous is False
    assert result.guidance == ""

