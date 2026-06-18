# Build Notes

Short summary of key engineering decisions made while building this app.

## Indicator backend: pandas_ta (primary) + native fallback
- **Dependency reality:** `pandas_ta==0.4.71b0` *requires* `numpy>=2.2.6`, which
  in turn pulls **pandas 3.x**. The spec's suggested pins
  (`numpy>=1.26,<2.1`, `pandas>=2.2,<2.3`) are therefore **not co-installable**
  with that pandas_ta build (`pip` raises `ResolutionImpossible`).
- **Resolution:** verified the actually-installable, mutually-compatible set —
  `pandas 3.0.x + numpy 2.2.x + pandas_ta 0.4.71b0` — and confirmed both
  `df.ta.rsi()` and `df.ta.macd()` work. `requirements.txt` pins
  `pandas>=2.2,<3.1`, `numpy>=2.0,<2.3`, `pandas_ta==0.4.71b0`, which resolves
  cleanly and is reproducible on Railway.
- **Chosen path:** `indicators.py` uses **pandas_ta** when present and falls
  back to a **native NumPy/pandas** Wilder-RSI / EMA-MACD implementation with
  IDENTICAL output column names (`rsi, macd, macd_signal, macd_hist`). The two
  paths are unit-tested to agree to < 1e-6. `INDICATOR_BACKEND` records which
  path is active and is shown in the UI. This keeps the rest of the app
  indifferent to the backend and guarantees the app still runs even if a future
  pandas_ta/numpy combination breaks.
- pandas 3.0's copy-on-write quirks were avoided by treating indicator inputs as
  immutable (we compute on `.reset_index(drop=True)` copies and assign by
  `.values`).

## Pure engines
`indicators.py` and `screen_engine.py` have **no web/DB imports** — pandas in,
DataFrame out — so they are directly unit-testable and reusable.

## RSI fixture test
The classic StockCharts "first RSI = 70.46" uses an **SMA-seeded** Wilder RSI.
pandas_ta and our native impl use the standard **recursive (EWM-seeded)** Wilder
RSI, which differs only during warm-up. The fixture test therefore validates
against an **independent hand-derived EWM-Wilder reference** (not a tautology),
plus bounds and monotonic-trend sanity checks.

## Persistence & secrets
- SQLite with `DB_PATH` env (default `/data/app.db` for a Railway volume,
  automatic fallback to `./app.db`). Tables: settings, api_keys, dictionaries,
  universes, snapshots — all versioned where relevant.
- API keys encrypted at rest with **Fernet** keyed from `APP_SECRET` (a stable
  random salt is persisted next to the DB if `APP_SECRET` is unset). Keys are
  masked (last 4 chars) in the UI, never logged, and **env vars take precedence**.

## Templating note
Newer Starlette requires `TemplateResponse(request, name, context)`. All routes
use that signature.

## Demo mode
`sample_data/_gen_prices.py` generates a deterministic 250-day, 13-ticker series
engineered so several names are clearly oversold (RSI<30, sharp drop) and
several clearly overbought (RSI>70, sharp rally), with idiosyncratic examples
(BABA-CN, BIDU-CN, PDD-CN) that diverge from their sub-industry peers, plus a
below-floor microcap (NANO-CN). Demo data auto-seeds on first run and via a
**Load demo data** button.

## LLM layer
Pluggable `LLMProvider` ABC with Perplexity Sonar, Anthropic Claude, and
DeepSeek implementations, built from settings via a registry. Strictly optional
and key-gated; all provider errors are caught so analysis **never crashes the
screen**. Prompts instruct the model to do qualitative synthesis only.

## Tests
39 pytest tests cover: z-score math, RSI & MACD vs fixture, native↔pandas_ta
equivalence, non-overlapping window logic, peer-divergence tagging,
`generate_formula`, BOTH formula-layout generators + xlsx round-trip,
dictionary-version validation (incl. rejection keeps prior active), encryption /
masking / env-precedence, and a mocked + failing LLM provider call. A full
demo-flow test asserts both ranked lists are non-empty and |z|-ranked.
