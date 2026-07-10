from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, MutableMapping
from typing import Any

from .models import Job, JobCancelled


class JobService:
    """Coordinates background job lifecycle against a caller-owned registry."""

    def __init__(
        self,
        jobs: MutableMapping[str, Job],
        lock: threading.Lock,
        *,
        append_log: Callable[[str, str], None],
        terminate_process: Callable[[Any], None],
    ) -> None:
        self._jobs = jobs
        self._lock = lock
        self._append_log = append_log
        self._terminate_process = terminate_process

    def start(self, name: str, target: Callable[[str], dict[str, Any] | None]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], name=name)
        with self._lock:
            self._jobs[job.id] = job

        def runner() -> None:
            try:
                self._append_log(job.id, f"job_start: {name}")
                result = target(job.id) or {}
                with self._lock:
                    if job.status == "cancel_requested":
                        self._finish_cancelled(job)
                        return
                    job.result = result
                    job.status = "done"
                    job.current_process = None
                    job.logs.append("job_done")
                    job.updated_at = time.time()
            except JobCancelled:
                with self._lock:
                    self._finish_cancelled(job)
            except Exception as exc:
                with self._lock:
                    if job.status == "cancel_requested":
                        self._finish_cancelled(job)
                    else:
                        job.status = "failed"
                        job.error = str(exc)
                        job.current_process = None
                        job.logs.append(f"job_failed: {exc}")
                        job.updated_at = time.time()

        threading.Thread(target=runner, daemon=True).start()
        return job

    def cancel(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if job.status not in {"running", "cancel_requested"}:
                return job
            job.status = "cancel_requested"
            job.updated_at = time.time()
            process = job.current_process
        self._append_log(job_id, "job_cancel_requested")
        if process and process.poll() is None:
            self._terminate_process(process)
        with self._lock:
            if job.status == "cancel_requested" and (process is None or process.poll() is not None):
                self._finish_cancelled(job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
            return [job.to_dict() for job in jobs]

    @staticmethod
    def _finish_cancelled(job: Job) -> None:
        job.status = "cancelled"
        job.current_process = None
        if not job.logs or job.logs[-1] != "job_cancelled":
            job.logs.append("job_cancelled")
        job.updated_at = time.time()
