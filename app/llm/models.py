"""Single source of truth for selectable LLM model IDs per provider.

Current as of June 2026. Each entry: (model_id, human_label).
The FIRST entry per provider is the recommended default.
"""
from __future__ import annotations

PROVIDER_MODELS = {
    "perplexity": [
        ("sonar", "Sonar (fast, web-grounded)"),
        ("sonar-pro", "Sonar Pro (200K ctx, high accuracy)"),
        ("sonar-reasoning", "Sonar Reasoning"),
        ("sonar-reasoning-pro", "Sonar Reasoning Pro (CoT + web)"),
        ("sonar-deep-research", "Sonar Deep Research"),
        ("r1-1776", "R1-1776 (offline, no web)"),
    ],
    "anthropic": [
        ("claude-opus-4-8", "Claude Opus 4.8 (most capable)"),
        ("claude-sonnet-4-6", "Claude Sonnet 4.6 (balanced default)"),
        ("claude-haiku-4-5", "Claude Haiku 4.5 (fast/cheap)"),
        ("claude-fable-5", "Claude Fable 5 (frontier)"),
        ("claude-opus-4-7", "Claude Opus 4.7 (legacy)"),
        ("claude-opus-4-6", "Claude Opus 4.6 (legacy)"),
    ],
    "deepseek": [
        ("deepseek-v4-pro", "DeepSeek V4 Pro (max capability, 1M ctx)"),
        ("deepseek-v4-flash", "DeepSeek V4 Flash (speed-optimized)"),
        ("deepseek-chat", "deepseek-chat (legacy alias, retires 2026-07-24)"),
        ("deepseek-reasoner", "deepseek-reasoner (legacy alias, retires 2026-07-24)"),
    ],
}

# First entry per provider is the recommended default model id.
DEFAULT_MODEL = {p: m[0][0] for p, m in PROVIDER_MODELS.items()}


# ---------------------------------------------------------------------------
# Anthropic capability quirks (June 2026).
#
# Newer Anthropic models deprecated/rejected the `temperature` sampling
# parameter and manual thinking budgets: sending `temperature` returns a
# 400 invalid_request_error ("`temperature` is deprecated for this model.").
# This applies to Opus 4.7+, Opus 4.8, and the Fable/Mythos 5 frontier tier.
# Sonnet 4.6 and Haiku 4.5 still accept `temperature`.
#
# We omit `temperature` for these models up front, AND the client also
# auto-retries without it if the API reports the param is unsupported, so the
# app stays forward-compatible as more models drop the parameter.
# ---------------------------------------------------------------------------
ANTHROPIC_NO_TEMPERATURE = {
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-fable-5",
    "claude-mythos-5",
}


def anthropic_supports_temperature(model: str) -> bool:
    return (model or "").strip() not in ANTHROPIC_NO_TEMPERATURE


# ---------------------------------------------------------------------------
# Pricing (USD per 1,000,000 tokens) — current as of June 2026.
#
# IMPORTANT CAVEATS:
#  - These are TOKEN-based list prices only. Perplexity ALSO charges
#    per-request fees (and Sonar Deep Research adds citation/reasoning fees);
#    those are NOT included in token-based estimates below.
#  - DeepSeek rates are approximate/promotional cache-miss list prices and may
#    change; off-peak discounts are not modeled.
# ---------------------------------------------------------------------------
PRICING = {
    # perplexity (per 1M tokens) — token cost only; request fees excluded.
    "sonar": {"in": 1.0, "out": 1.0},
    "sonar-pro": {"in": 3.0, "out": 15.0},
    "sonar-reasoning": {"in": 1.0, "out": 5.0},
    "sonar-reasoning-pro": {"in": 2.0, "out": 8.0},
    "sonar-deep-research": {"in": 2.0, "out": 8.0},
    "r1-1776": {"in": 2.0, "out": 8.0},
    # anthropic (per 1M tokens)
    "claude-opus-4-8": {"in": 5.0, "out": 25.0},
    "claude-opus-4-7": {"in": 5.0, "out": 25.0},
    "claude-opus-4-6": {"in": 5.0, "out": 25.0},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0},
    "claude-fable-5": {"in": 10.0, "out": 50.0},
    # deepseek (per 1M tokens) — approximate / promotional; subject to change.
    "deepseek-v4-pro": {"in": 0.435, "out": 0.87},
    "deepseek-v4-flash": {"in": 0.14, "out": 0.28},
    "deepseek-chat": {"in": 0.14, "out": 0.28},
    "deepseek-reasoner": {"in": 0.14, "out": 0.28},
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD token cost for a single call.

    Returns 0.0 for an unknown model (no pricing entry). Excludes any
    per-request / search / citation fees (notably Perplexity request fees).
    """
    rate = PRICING.get((model or "").strip())
    if not rate:
        return 0.0
    try:
        pt = max(0, int(prompt_tokens or 0))
        ct = max(0, int(completion_tokens or 0))
    except Exception:
        return 0.0
    return (pt / 1_000_000.0) * rate["in"] + (ct / 1_000_000.0) * rate["out"]
