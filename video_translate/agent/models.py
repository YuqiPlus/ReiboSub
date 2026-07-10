from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSession:
    """Mutable state for one user-facing translation workflow."""

    id: str
    status: str = "running"
    phase: str = "created"
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    question: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "phase": self.phase,
            "payload": self.payload,
            "result": self.result,
            "question": self.question,
            "logs": self.logs[-500:],
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cancellable": self.status in {"running", "waiting"},
            "retryable": self.status == "failed",
        }
