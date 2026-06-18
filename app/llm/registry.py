"""Build a provider from settings; gracefully disable when no key."""
from __future__ import annotations

from typing import Optional

from .anthropic_client import AnthropicProvider
from .base import LLMProvider
from .deepseek import DeepSeekProvider
from .perplexity import PerplexityProvider

_REGISTRY = {
    "perplexity": PerplexityProvider,
    "anthropic": AnthropicProvider,
    "deepseek": DeepSeekProvider,
}


def build_provider(provider: str, api_key: str, model: str = "", **opts) -> Optional[LLMProvider]:
    cls = _REGISTRY.get(provider)
    if cls is None:
        return None
    if not api_key:
        return None
    return cls(api_key=api_key, model=model, **opts)


def available_providers() -> list[str]:
    return list(_REGISTRY.keys())
