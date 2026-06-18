"""ITEM 3 — pricing/estimate_cost + usage ledger aggregation."""
from app import settings_store as ss
from app.llm.models import estimate_cost


def test_estimate_cost_known_model():
    # claude-sonnet-4-6: in 3 / out 15 per 1M tokens.
    cost = estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert abs(cost - (3.0 + 15.0)) < 1e-9
    # sonar: 1/1
    assert abs(estimate_cost("sonar", 2_000_000, 0) - 2.0) < 1e-9


def test_estimate_cost_unknown_model_is_zero():
    assert estimate_cost("totally-made-up", 1_000_000, 1_000_000) == 0.0
    assert estimate_cost("", 5, 5) == 0.0


def test_log_usage_and_summary(temp_db):
    ss.log_usage("anthropic", "claude-sonnet-4-6", "sidebar",
                 {"prompt_tokens": 1000, "completion_tokens": 500}, ok=True, db_path=temp_db)
    ss.log_usage("perplexity", "sonar", "ping",
                 {"prompt_tokens": 10, "completion_tokens": 2}, ok=True, db_path=temp_db)
    ss.log_usage("perplexity", "sonar", "ping", None, ok=False, note="400 boom", db_path=temp_db)

    summ = ss.get_usage_summary(temp_db)
    assert summ["total_calls"] == 3
    assert summ["total_tokens"] == 1000 + 500 + 10 + 2 + 0
    # cost: sonnet (1000/1e6*3 + 500/1e6*15) + sonar(10/1e6*1 + 2/1e6*1)
    exp = (1000/1e6*3 + 500/1e6*15) + (10/1e6*1 + 2/1e6*1)
    assert abs(summ["total_cost_usd"] - exp) < 1e-9
    # breakdown grouped; one failed perplexity/ping row
    by = {(b["provider"], b["model"], b["section"]): b for b in summ["breakdown"]}
    assert by[("perplexity", "sonar", "ping")]["calls"] == 2
    assert by[("perplexity", "sonar", "ping")]["fails"] == 1


def test_recent_and_clear_usage(temp_db):
    for i in range(3):
        ss.log_usage("deepseek", "deepseek-v4-pro", "per_name",
                     {"prompt_tokens": i, "completion_tokens": i}, ok=True, db_path=temp_db)
    rec = ss.recent_usage(10, db_path=temp_db)
    assert len(rec) == 3
    removed = ss.clear_usage(temp_db)
    assert removed == 3
    assert ss.get_usage_summary(temp_db)["total_calls"] == 0
    assert ss.recent_usage(10, db_path=temp_db) == []


def test_log_usage_tolerates_missing_usage(temp_db):
    # None usage dict -> zero tokens, zero cost, still logged.
    ss.log_usage("anthropic", "claude-opus-4-8", "portfolio", None, ok=False, db_path=temp_db)
    summ = ss.get_usage_summary(temp_db)
    assert summ["total_calls"] == 1
    assert summ["total_tokens"] == 0
    assert summ["total_cost_usd"] == 0.0
