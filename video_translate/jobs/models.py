from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    """Mutable state for a cancellable background job."""

    id: str
    name: str
    status: str = "running"
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    current_process: subprocess.Popen[str] | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "logs": self.logs[-500:],
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cancellable": self.status in {"running", "cancel_requested"},
        }


class JobCancelled(RuntimeError):
    """Signals that a job ended because the user requested cancellation."""
