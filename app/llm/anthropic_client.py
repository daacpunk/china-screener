"""Anthropic Claude provider."""
from __future__ import annotations

from typing import Any

from .base import LLMError, LLMProvider


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def complete(self, prompt: str, **opts: Any) -> str:
        if not self.available:
            raise LLMError("no API key")
        try:
            import anthropic
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"anthropic SDK not installed: {e}")
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            msg = client.messages.create(
                model=self.model or "claude-3-5-sonnet-latest",
                max_tokens=int(opts.get("max_tokens", 800)),
                temperature=float(opts.get("temperature", 0.2)),
                messages=[{"role": "user", "content": prompt}],
            )
            parts = []
            for block in msg.content:
                txt = getattr(block, "text", None)
                if txt:
                    parts.append(txt)
            return "\n".join(parts)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Anthropic error: {e}")
