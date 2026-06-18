"""Anthropic Claude provider."""
from __future__ import annotations

from typing import Any

from .base import LLMError, LLMProvider
from .models import DEFAULT_MODEL


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
                model=self.model or DEFAULT_MODEL["anthropic"],
                max_tokens=int(opts.get("max_tokens", 800)),
                temperature=float(opts.get("temperature", 0.2)),
                messages=[{"role": "user", "content": prompt}],
            )
            self._capture_usage(msg)
            parts = []
            for block in msg.content:
                txt = getattr(block, "text", None)
                if txt:
                    parts.append(txt)
            return "\n".join(parts)
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001
            # The SDK's exception message (str(e)) carries the real cause.
            raise LLMError(f"Anthropic error: {e}")

    def _capture_usage(self, msg: Any) -> None:
        try:
            u = getattr(msg, "usage", None)
            self.last_usage = {
                "prompt_tokens": int(getattr(u, "input_tokens", 0) or 0),
                "completion_tokens": int(getattr(u, "output_tokens", 0) or 0),
            }
        except Exception:
            self.last_usage = None
