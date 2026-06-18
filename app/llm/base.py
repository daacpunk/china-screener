"""LLMProvider abstraction. Providers are strictly optional and never crash
the screen — all errors are caught and surfaced as text.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, api_key: str, model: str, **opts: Any):
        self.api_key = api_key
        self.model = model
        self.opts = opts

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @abstractmethod
    def complete(self, prompt: str, **opts: Any) -> str:
        """Return completion text. Should raise LLMError on failure."""
        raise NotImplementedError

    def ping(self) -> dict:
        """Lightweight connectivity check. Never raises."""
        if not self.available:
            return {"ok": False, "detail": "no API key configured"}
        try:
            out = self.complete("Reply with the single word: pong", max_tokens=8)
            return {"ok": True, "detail": (out or "").strip()[:50]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"[:200]}
