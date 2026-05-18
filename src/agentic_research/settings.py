from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "configs"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"


def resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def load_yaml_config(path_or_name: str | Path) -> dict[str, Any]:
    """Load a YAML config from configs/ or a project-relative path."""
    path = Path(path_or_name)
    candidates: list[Path] = []

    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(CONFIG_DIR / path)
        candidates.append(resolve_project_path(path))
        if path.suffix == "":
            candidates.append(CONFIG_DIR / f"{path}.yaml")
            candidates.append(CONFIG_DIR / f"{path}.yml")

    for candidate in candidates:
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
            return data or {}

    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Config not found: {path_or_name}. Searched: {searched}")


def get_artifact_dir() -> Path:
    workflow = load_yaml_config("workflow.yaml").get("workflow", {})
    artifact_dir = workflow.get("artifact_dir", "runs")
    return resolve_project_path(artifact_dir)
