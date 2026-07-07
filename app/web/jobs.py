"""Tiny in-process background-job registry (stdlib threading only).

Used to move slow, multi-minute LLM work (research-note generation) OFF the
HTTP request thread so the request returns immediately and the UI can poll for
the result. No external deps, no persistence — jobs live in a module-level dict
guarded by a Lock and are capped so memory can't grow unbounded.

Design goals:
- Thread-safe: all reads/writes to the registry go through a single Lock.
- Never raise: start_job / get_job never propagate exceptions to the caller;
  a worker that raises is recorded as status="error" (the process survives).
- Bounded: keep at most ``_MAX_JOBS`` entries; oldest are dropped first.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

# Keep at most this many jobs in memory; oldest are evicted first.
_MAX_JOBS = 50

_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}


def _cleanup_locked() -> None:
    """Drop oldest jobs until we're at/under the cap. Caller must hold _lock."""
    if len(_jobs) <= _MAX_JOBS:
        return
    # Sort by start time ascending; evict the oldest surplus entries.
    ordered = sorted(_jobs.items(), key=lambda kv: kv[1].get("started", 0.0))
    surplus = len(_jobs) - _MAX_JOBS
    for job_id, _ in ordered[:surplus]:
        _jobs.pop(job_id, None)


def start_job(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Run ``fn(*args, **kwargs)`` in a daemon thread; return a job id.

    Status transitions: "running" -> "done" (with result) or "error" (with a
    message). Never raises — a failure to spawn is itself recorded as an error
    job so the caller always gets a usable id.
    """
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "started": time.time(),
        }
        _cleanup_locked()

    def _run() -> None:
        try:
            out = fn(*args, **kwargs)
            with _lock:
                rec = _jobs.get(job_id)
                if rec is not None:
                    rec["status"] = "done"
                    rec["result"] = out
        except Exception as e:  # noqa: BLE001 — worker must never crash the process
            with _lock:
                rec = _jobs.get(job_id)
                if rec is not None:
                    rec["status"] = "error"
                    rec["error"] = str(e) or e.__class__.__name__

    try:
        t = threading.Thread(target=_run, name=f"job-{job_id[:8]}", daemon=True)
        t.start()
    except Exception as e:  # noqa: BLE001 — even thread spawn failure degrades gracefully
        with _lock:
            rec = _jobs.get(job_id)
            if rec is not None:
                rec["status"] = "error"
                rec["error"] = f"could not start job: {e}"
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Return a shallow copy of the job record, or None if unknown. Never raises."""
    if not job_id:
        return None
    with _lock:
        rec = _jobs.get(job_id)
        return dict(rec) if rec is not None else None
