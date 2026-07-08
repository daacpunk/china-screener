"""Background research-note generation: in-process job registry + HTMX polling.

Covers:
  (a) jobs.start_job / get_job running->done with result; a raising fn ->
      status "error" (no crash); job cap evicts the oldest.
  (b) POST /analysis/note with a provider configured -> PENDING partial with a
      job id + hx-get poller; with NO provider -> inline set-a-key note (no job).
  (c) GET /analysis/note/status?job=<id>: running -> pending partial w/ poller;
      done -> final note html (candidate table / rendered markdown) NO poller;
      unknown id -> expired message.

rn.generate_note is monkeypatched to a fast stub so tests are quick + determinstic.
"""
import time

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.web import jobs
from app.web import routes_analysis as ra

client = TestClient(app)


# ----------------------------------------------------------------------------
# (a) jobs registry
# ----------------------------------------------------------------------------
def test_start_job_running_to_done():
    def _fn(x):
        return {"value": x * 2}

    jid = jobs.start_job(_fn, 21)
    assert isinstance(jid, str) and jid
    # Poll until done (fast fn; generous bound).
    for _ in range(100):
        rec = jobs.get_job(jid)
        if rec and rec["status"] == "done":
            break
        time.sleep(0.01)
    rec = jobs.get_job(jid)
    assert rec is not None
    assert rec["status"] == "done"
    assert rec["result"] == {"value": 42}
    assert rec["error"] is None


def test_start_job_error_no_crash():
    def _boom():
        raise ValueError("kaboom")

    jid = jobs.start_job(_boom)
    for _ in range(100):
        rec = jobs.get_job(jid)
        if rec and rec["status"] == "error":
            break
        time.sleep(0.01)
    rec = jobs.get_job(jid)
    assert rec is not None
    assert rec["status"] == "error"
    assert "kaboom" in (rec["error"] or "")
    assert rec["result"] is None


def test_get_job_unknown_returns_none():
    assert jobs.get_job("does-not-exist") is None
    assert jobs.get_job("") is None


def test_job_cap_evicts_oldest():
    # Fill well past the cap with instant no-op jobs, then confirm the registry
    # is bounded and the very first ids were evicted.
    first_ids = []
    for i in range(jobs._MAX_JOBS + 20):
        jid = jobs.start_job(lambda: None)
        if i < 5:
            first_ids.append(jid)
    # Let workers finish.
    time.sleep(0.2)
    with jobs._lock:
        n = len(jobs._jobs)
    assert n <= jobs._MAX_JOBS
    # The earliest-started jobs should have been dropped.
    assert all(jobs.get_job(j) is None for j in first_ids)


# ----------------------------------------------------------------------------
# Helpers: a non-empty fake screen + fast generate_note stub
# ----------------------------------------------------------------------------
def _fake_screen():
    df = pd.DataFrame([{"ticker": "AAA", "name": "Alpha", "sector": "Tech"}])
    return {"master": df, "oversold": df, "overbought": df,
            "skipped": pd.DataFrame(),
            "meta": {"asof": "2026-06-20", "staleness_days": 3},
            "_empty": False}


class _FakeProvider:
    name = "anthropic"
    available = True


def _fast_generate_note(*args, **kwargs):
    return {
        "markdown": "# Research\n\nBody text here.",
        "candidates": [{"ticker": "AAA", "name": "Alpha", "side": "long",
                        "sector": "Tech", "rank_z": -2.0, "peer_relative_z": -1.5,
                        "rsi": 25.0, "reversion_score": 0.7, "fade_score": None,
                        "dislocation_type": "IDIOSYNCRATIC", "verdict": "MECHANICAL_DISLOCATION",
                        "source": "event", "event_date": "2026-06-18"}],
        "asof": "2026-06-20", "provider": "anthropic",
        "error": None, "notice": None,
    }


# ----------------------------------------------------------------------------
# (b) POST /analysis/note
# ----------------------------------------------------------------------------
def test_post_note_with_provider_returns_pending_partial(temp_db, monkeypatch):
    monkeypatch.setattr(ra, "run_active_screen", _fake_screen)
    monkeypatch.setattr(ra, "_resolve_note_provider", lambda provider="": _FakeProvider())
    monkeypatch.setattr(ra, "build_fallback_providers", lambda name: [])
    monkeypatch.setattr(ra, "resolve_web_provider", lambda: None)
    # Slow-ish stub so the job is still 'running' when the response returns.
    monkeypatch.setattr(ra.rn, "generate_note",
                        lambda *a, **k: (time.sleep(1.0) or _fast_generate_note()))

    r = client.post("/analysis/note", data={"max_longs": 3, "max_shorts": 3})
    assert r.status_code == 200
    # Pending partial: has the poller with a job id, and NO rendered note yet.
    assert "note-poll" in r.text
    assert "/analysis/note/status?job=" in r.text
    # Repeating poll trigger on the STABLE outer #note-poll (verified in a real
    # browser: 'load delay' fires only ONCE and stops polling; 'every 2s' on an
    # element that is never self-replaced during polling repeats reliably).
    assert 'hx-trigger="every 2s"' in r.text
    # Stable outer poller: trigger swaps the INNER content, never itself.
    assert 'hx-target="#note-poll-inner"' in r.text
    assert "note-poll-inner" in r.text
    assert "Body text here" not in r.text


def test_post_note_no_provider_returns_inline_set_a_key(temp_db, monkeypatch):
    monkeypatch.setattr(ra, "run_active_screen", _fake_screen)
    monkeypatch.setattr(ra, "_resolve_note_provider", lambda provider="": None)
    monkeypatch.setattr(ra, "build_fallback_providers", lambda name: [])
    monkeypatch.setattr(ra, "resolve_web_provider", lambda: None)

    r = client.post("/analysis/note", data={"max_longs": 2, "max_shorts": 2})
    assert r.status_code == 200
    # Inline path: no background poller, and the candidate table renders inline.
    assert "note-poll" not in r.text
    assert "/analysis/note/status?job=" not in r.text
    # generate_note's real no-provider path yields a set-a-key error + candidates.
    assert ("Settings" in r.text) or ("Selected candidates" in r.text)


# ----------------------------------------------------------------------------
# (c) GET /analysis/note/status
# ----------------------------------------------------------------------------
def test_status_unknown_job_returns_expired(temp_db, monkeypatch):
    monkeypatch.setattr(ra, "run_active_screen", _fake_screen)
    r = client.get("/analysis/note/status?job=bogus-id")
    assert r.status_code == 200
    assert "expired" in r.text.lower()
    # Polling must STOP: OOB-replaces the poller and carries no live poll trigger.
    assert "hx-swap-oob" in r.text
    assert "hx-get" not in r.text and "hx-trigger" not in r.text


def test_status_running_returns_pending_with_poller(temp_db, monkeypatch):
    monkeypatch.setattr(ra, "run_active_screen", _fake_screen)
    # Directly seed a running job in the registry.
    jid = jobs.start_job(lambda: (time.sleep(2.0) or {}))
    r = client.get(f"/analysis/note/status?job={jid}")
    assert r.status_code == 200
    # Running: returns ONLY the inner spinner (swapped into #note-poll-inner);
    # the stable outer #note-poll poller stays in the DOM and keeps polling.
    assert "note-generating" in r.text
    assert "hx-swap-oob" not in r.text  # not a stop signal


def test_status_done_returns_final_note_no_poller(temp_db, monkeypatch):
    monkeypatch.setattr(ra, "run_active_screen", _fake_screen)
    # Patch generate_note BEFORE starting the job so the worker uses the stub.
    monkeypatch.setattr(ra.rn, "generate_note", _fast_generate_note)
    # Run a fast job to completion, then check the status render.
    jid = jobs.start_job(
        ra._note_job, _FakeProvider(), [], [], [], {}, 2, 2, True, False,
        "2026-06-20", [], None,
    )
    for _ in range(200):
        rec = jobs.get_job(jid)
        if rec and rec["status"] == "done":
            break
        time.sleep(0.01)
    rec = jobs.get_job(jid)
    assert rec and rec["status"] == "done"
    r = client.get(f"/analysis/note/status?job={jid}")
    assert r.status_code == 200
    # Final note: rendered markdown + candidate table, delivered via an OOB swap
    # that REPLACES the poller (removing the live trigger -> polling stops).
    assert "hx-swap-oob" in r.text
    assert "hx-trigger" not in r.text
    assert "Selected candidates" in r.text
    assert "Body text here" in r.text


def test_status_error_returns_clean_error_no_poller(temp_db, monkeypatch):
    monkeypatch.setattr(ra, "run_active_screen", _fake_screen)

    def _boom(*a, **k):
        raise RuntimeError("triage exploded")

    jid = jobs.start_job(_boom)
    for _ in range(200):
        rec = jobs.get_job(jid)
        if rec and rec["status"] == "error":
            break
        time.sleep(0.01)
    r = client.get(f"/analysis/note/status?job={jid}")
    assert r.status_code == 200
    # Error: OOB-replaces the poller (stops polling), no live trigger.
    assert "hx-swap-oob" in r.text
    assert "hx-trigger" not in r.text
    assert "failed" in r.text.lower()
