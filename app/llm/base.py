"""LLMProvider abstraction. Providers are strictly optional and never crash
the screen — all errors are caught and surfaced as text.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, api_key: str, model: str, **opts: Any):
        # A trailing newline/whitespace in a pasted key is a very common cause
        # of 400/401 errors — strip it once, here, for all providers.
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.opts = opts
        # Populated by complete() after each call (do NOT change return type).
        # {"prompt_tokens": int, "completion_tokens": int} or None.
        self.last_usage: Optional[dict] = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @abstractmethod
    def complete(self, prompt: str, **opts: Any) -> str:
        """Return completion text. Should raise LLMError on failure."""
        raise NotImplementedError

    def ping(self) -> dict:
        """Lightweight connectivity check. Never raises.

        Returns {ok, detail, model, status?}. On success ``detail`` is a short
        echo; on failure ``detail`` is the FULL surfaced error (status + body)
        so the Settings UI can show an actionable message.
        """
        model = self.model or "(provider default)"
        if not self.available:
            return {"ok": False, "detail": "no API key configured", "model": model}
        self.last_usage = None
        try:
            # Small max_tokens + generous timeout: some reasoning/deep-research
            # models are slow but must still answer a minimal valid request.
            out = self.complete(
                "Reply with the single word: pong",
                max_tokens=32,
                timeout=60,
            )
            return {"ok": True, "detail": (out or "").strip()[:200] or "(empty)",
                    "model": model}
        except Exception as e:  # noqa: BLE001
            # Surface the FULL error (already includes status + body for httpx
            # providers); do not truncate aggressively here.
            return {"ok": False, "detail": f"{e}"[:600], "model": model}
