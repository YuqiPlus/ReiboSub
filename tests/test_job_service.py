from __future__ import annotations

import threading
import time

from video_translate.jobs import Job, JobService


def _service(jobs: dict[str, Job]) -> JobService:
    lock = threading.Lock()

    def append_log(job_id: str, line: str) -> None:
        with lock:
            jobs[job_id].logs.append(line)

    return JobService(jobs, lock, append_log=append_log, terminate_process=lambda process: None)


def _wait_for_status(service: JobService, job_id: str, expected_status: str) -> Job:
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        job = service.get(job_id)
        if job and job.status == expected_status:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {expected_status}")


def test_job_service_marks_successful_jobs_done():
    jobs: dict[str, Job] = {}
    service = _service(jobs)
    completed = threading.Event()

    def target(job_id: str) -> dict[str, bool]:
        completed.set()
        return {"ok": True}

    job = service.start("demo", target)

    assert completed.wait(timeout=1)
    assert _wait_for_status(service, job.id, "done").result == {"ok": True}


def test_job_service_lists_newest_jobs_first():
    jobs = {
        "older": Job(id="older", name="older", created_at=1),
        "newer": Job(id="newer", name="newer", created_at=2),
    }

    assert [job["id"] for job in _service(jobs).list()] == ["newer", "older"]
