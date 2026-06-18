"""DeepSeek provider (OpenAI-compatible chat completions over httpx)."""
from __future__ import annotations

from typing import Any

import httpx

from .base import LLMError, LLMProvider
from .models import DEFAULT_MODEL

_API = "https://api.deepseek.com/chat/completions"


def _truncate_body(r: httpx.Response, limit: int = 300) -> str:
    try:
        return str(r.json())[:limit]
    except Exception:
        try:
            return (r.text or "")[:limit]
        except Exception:
            return "(no response body)"


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def complete(self, prompt: str, **opts: Any) -> str:
        if not self.available:
            raise LLMError("no API key")
        payload = {
            "model": self.model or DEFAULT_MODEL["deepseek"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(opts.get("max_tokens", 800)),
            "temperature": float(opts.get("temperature", 0.2)),
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=opts.get("timeout", 60)) as client:
                r = client.post(_API, json=payload, headers=headers)
                if r.status_code >= 400:
                    raise LLMError(
                        f"DeepSeek {r.status_code}: {_truncate_body(r)}"
                    )
                data = r.json()
                self._capture_usage(data)
                return data["choices"][0]["message"]["content"]
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"DeepSeek error: {e}")

    def _capture_usage(self, data: dict) -> None:
        try:
            u = data.get("usage") or {}
            self.last_usage = {
                "prompt_tokens": int(u.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(u.get("completion_tokens", 0) or 0),
            }
        except Exception:
            self.last_usage = None
