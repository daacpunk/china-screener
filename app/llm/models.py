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
