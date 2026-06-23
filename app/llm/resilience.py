"""Retry-with-backoff and provider-fallback wrappers for LLM calls.

Dependency-free (stdlib time/random only). Providers wrap their failures as
``LLMError(str)`` (see base.py / anthropic_client.py / perplexity.py /
deepseek.py), so detection must work both on real exception status attributes
AND on the stringified message. Never adds a hard dependency (no tenacity).
"""
from __future__ import annotations

import random
import time
from typing import Any, List, Optional, Tuple

from .base import LLMError, LLMProvider

# HTTP statuses that indicate a transient/overloaded condition worth retrying.
RETRYABLE_STATUS = {429, 500, 502, 503, 529}

# Substrings (case-insensitive) that signal a transient/retryable error even
# when the provider has flattened everything into an LLMError(str).
_RETRYABLE_SUBSTRINGS = (
    "529", "429", "overloaded", "rate limit", "rate_limit",
    "timeout", "temporarily", "502", "503", "500",
)

# Substrings (case-insensitive) that mark a PERMANENT error — these must fail
# fast and never be retried, even if a retryable token also appears.
_PERMANENT_SUBSTRINGS = (
    "invalid api key", "authentication", "not_found", "404",
    "401", "403", "400",
)


def _status_code(exc: Exception) -> Optional[int]:
    """Best-effort HTTP status extraction from an exception."""
    code = getattr(exc, "status_code", None)
    if code is None:
        resp = getattr(exc, "response", None)
        code = getattr(resp, "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def is_retryable(exc: Exception) -> bool:
    """True when an exception looks like a transient/overloaded condition.

    Auth/permanent signals win: if both a 4xx-auth signal and a retry signal
    appear, treat it as permanent (no retry).
    """
    text = str(exc).lower()

    # Permanent (auth/bad-request/not-found) wins over any retry signal.
    code = _status_code(exc)
    if code is not None and code in {400, 401, 403, 404}:
        return False
    if any(p in text for p in _PERMANENT_SUBSTRINGS):
        return False

    if code is not None and code in RETRYABLE_STATUS:
        return True
    return any(s in text for s in _RETRYABLE_SUBSTRINGS)


def complete_with_retry(
    provider: LLMProvider,
    prompt: str,
    *,
    max_attempts: int = 4,
    base_delay: float = 0.6,
    max_delay: float = 8.0,
    **opts: Any,
) -> str:
    """Call provider.complete, retrying retryable errors with backoff+jitter.

    Non-retryable (e.g. auth) errors re-raise immediately. After the final
    attempt the last exception is re-raised.
    """
    for attempt in range(max_attempts):
        try:
            return provider.complete(prompt, **opts)
        except Exception as e:  # noqa: BLE001
            if not is_retryable(e) or attempt == max_attempts - 1:
                raise
            delay = min(max_delay, base_delay * (2 ** attempt))
            time.sleep(delay * random.uniform(0.5, 1.5))
    # Only reached if max_attempts < 1 (no call made).
    raise LLMError("complete_with_retry: max_attempts must be >= 1")


def complete_with_fallback(
    primary_provider: LLMProvider,
    prompt: str,
    *,
    fallback_providers: Optional[List[LLMProvider]] = None,
    section: str = "",
    max_attempts: int = 4,
    base_delay: float = 0.6,
    max_delay: float = 8.0,
    **opts: Any,
) -> Tuple[str, str]:
    """Try the primary with retry; on persistent overload, try fallbacks.

    Returns (text, provider_name_used) so callers can note which model answered.

    - Primary raises a RETRYABLE error after all attempts -> walk fallbacks in
      order, each via complete_with_retry, returning the first success + name.
    - Primary raises a NON-retryable error (e.g. bad key) -> re-raise (do NOT
      silently fall back; the user must fix their config).
    - All providers fail -> raise the last exception.
    """
    fallback_providers = fallback_providers or []
    try:
        text = complete_with_retry(
            primary_provider, prompt,
            max_attempts=max_attempts, base_delay=base_delay, max_delay=max_delay,
            **opts,
        )
        return text, getattr(primary_provider, "name", "")
    except Exception as primary_exc:  # noqa: BLE001
        # Permanent error on the primary: surface it, do not mask config issues.
        if not is_retryable(primary_exc):
            raise
        last_exc: Exception = primary_exc
        for fb in fallback_providers:
            if fb is None or not getattr(fb, "available", False):
                continue
            try:
                text = complete_with_retry(
                    fb, prompt,
                    max_attempts=max_attempts, base_delay=base_delay, max_delay=max_delay,
                    **opts,
                )
                return text, getattr(fb, "name", "")
            except Exception as e:  # noqa: BLE001
                last_exc = e
                continue
        raise last_exc
