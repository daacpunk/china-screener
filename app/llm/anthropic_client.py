"""Anthropic Claude provider."""
from __future__ import annotations

from typing import Any

from .base import LLMError, LLMProvider
from .models import DEFAULT_MODEL, anthropic_supports_temperature


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def complete(self, prompt: str, **opts: Any) -> str:
        if not self.available:
            raise LLMError("no API key")
        try:
            import anthropic
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"anthropic SDK not installed: {e}")
        model = self.model or DEFAULT_MODEL["anthropic"]
        client = anthropic.Anthropic(api_key=self.api_key)
        kwargs = {
            "model": model,
            "max_tokens": int(opts.get("max_tokens", 800)),
            "messages": [{"role": "user", "content": prompt}],
        }
        # Newer Claude models (Opus 4.7/4.8, Fable/Mythos 5) reject `temperature`
        # with a 400. Only send it for models known to accept it.
        if anthropic_supports_temperature(model):
            kwargs["temperature"] = float(opts.get("temperature", 0.2))

        def _call(kw):
            msg = client.messages.create(**kw)
            self._capture_usage(msg)
            parts = []
            for block in msg.content:
                txt = getattr(block, "text", None)
                if txt:
                    parts.append(txt)
            return "\n".join(parts)

        try:
            return _call(kwargs)
        except Exception as e:  # noqa: BLE001
            emsg = str(e)
            # Forward-compat: if the API reports a sampling/thinking param is
            # unsupported/deprecated, retry once without it.
            lowered = emsg.lower()
            if "temperature" in kwargs and (
                "temperature" in lowered
                and ("deprecat" in lowered or "unsupported" in lowered or "not supported" in lowered)
            ):
                try:
                    retry = dict(kwargs)
                    retry.pop("temperature", None)
                    return _call(retry)
                except Exception as e2:  # noqa: BLE001
                    raise LLMError(f"Anthropic error: {e2}")
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
