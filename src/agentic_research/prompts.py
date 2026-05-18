from __future__ import annotations

from pathlib import Path

from agentic_research.settings import PROJECT_ROOT, PROMPTS_DIR


def _markdown_name(name: str) -> str:
    return name if Path(name).suffix else f"{name}.md"


def _resolve_prompt_path(path_or_name: str | Path) -> Path:
    path = Path(path_or_name)
    candidates: list[Path] = []

    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(PROJECT_ROOT / path)
        candidates.append(PROMPTS_DIR / path)
        if path.suffix == "":
            candidates.append(PROMPTS_DIR / _markdown_name(str(path)))

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Prompt not found: {path_or_name}. Searched: {searched}")


def load_prompt(path_or_name: str | Path) -> str:
    """Load a prompt by absolute path, project-relative path, or prompt name."""
    return _resolve_prompt_path(path_or_name).read_text(encoding="utf-8")


def load_agent_prompt(agent_name: str) -> str:
    return load_prompt(PROMPTS_DIR / "agents" / _markdown_name(agent_name))


def load_policy_prompt(policy_name: str) -> str:
    return load_prompt(PROMPTS_DIR / "policies" / _markdown_name(policy_name))
