from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunLogger:
    """Append-only structured local run log."""

    def __init__(self, run_dir: Path, run_id: str) -> None:
        self.run_id = run_id
        self.path = run_dir / "run_log.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(
        self,
        event: str,
        *,
        stage: str | None = None,
        level: str = "info",
        message: str | None = None,
        **details: Any,
    ) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "level": level,
            "event": event,
            "stage": stage,
            "message": message,
            "details": details,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    def stage_start(self, stage: str, **details: Any) -> None:
        self.event("stage_start", stage=stage, **details)

    def stage_end(self, stage: str, **details: Any) -> None:
        self.event("stage_end", stage=stage, **details)

    def agent_call(self, agent_key: str, *, status: str, **details: Any) -> None:
        self.event("agent_call", stage=agent_key, status=status, **details)

    def tool_call(self, tool_name: str, *, status: str, **details: Any) -> None:
        self.event("tool_call", stage=tool_name, status=status, **details)

    def artifact(self, path: Path, **details: Any) -> None:
        self.event(
            "artifact_written",
            stage="artifacts",
            path=str(path),
            **details,
        )

    def error(self, error: BaseException, *, stage: str | None = None) -> None:
        self.event(
            "error",
            stage=stage,
            level="error",
            message=str(error),
            error_type=type(error).__name__,
        )
