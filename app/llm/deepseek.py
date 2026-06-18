"""DeepSeek provider (OpenAI-compatible chat completions over httpx)."""
from __future__ import annotations

from typing import Any

import httpx

from .base import LLMError, LLMProvider

_API = "https://api.deepseek.com/chat/completions"


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def complete(self, prompt: str, **opts: Any) -> str:
        if not self.available:
            raise LLMError("no API key")
        payload = {
            "model": self.model or "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(opts.get("max_tokens", 800)),
            "temperature": float(opts.get("temperature", 0.2)),
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=opts.get("timeout", 40)) as client:
                r = client.post(_API, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"DeepSeek error: {e}")
