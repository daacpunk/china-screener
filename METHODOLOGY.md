# Methodology

This document defines exactly how the screen computes its signals. All
parameters are configurable in **Settings → Screen parameters**; defaults are
shown in parentheses.

## 1. Universe (Step 1)
The active screening universe is:

```
active = (constituents passing the liquidity floor) ∪ (manual tickers)
```

- **Liquidity floor** (default 20-day ADV in USD > $10,000,000). Below-floor
  names are dropped from the screen but retained in a separate "below-floor /
  untradable" view and never deleted.
- **Manual tickers** are always included regardless of floor.
- Each name carries sector, GICS sub-industry, index weight, and below-floor tag.

## 2. Signals (Step 2)

### Non-overlapping horizon returns
Two horizons are measured so they do **not** overlap:

- **Horizon A — 1-week return**: return over the **last 5 trading days**,
  `r_A = P[-1] / P[-6] − 1`.
- **Horizon B — 1-month-ex-last-week**: return from **~21 trading days ago to
  ~5 trading days ago**, `r_B = P[-6] / P[-22] − 1`.

The two return *intervals* share only the single anchor point at day −5, so the
1-week move is measured independently of the prior 3-week move.

### Volatility-normalized z-score
Daily-return mean `μ` and volatility `σ` are estimated over a trailing window
(default **60** trading days, configurable 20–60). The horizon return is
standardized and scaled to the horizon length `h` by `√h`:

```
z = (r_horizon − μ_daily · h) / (σ_daily · √h)
```

A **composite z** blends Horizon A and B (default weights 0.5 / 0.5) and is the
ranking key. We rank by **|z| in both tails** — the goal is to surface the
extremes, not to rank toward the median.

### Reversion metrics
- **Distance from 20-day mean**: `(P − SMA20) / SMA20`, also expressed in σ
  units (`dist / σ_daily`).
- **RSI(14)** — Wilder's RSI (see §5).
- **MACD(12, 26, 9)** — state is *Bullish* if MACD line > signal line, else
  *Bearish*.

## 3. Idiosyncratic vs sector (Step 3)
For each name we compare its composite z to the **median composite z of its GICS
sub-industry peers**:

```
peer_relative_z = stock_z − peer_group_median_z
|peer_relative_z| ≥ divergence_threshold (default 1.0)  ⇒  IDIOSYNCRATIC
otherwise                                                ⇒  SECTOR / MACRO / POLICY
```

This separates single-name dislocations from sector- or macro-wide moves.

## 4. Playbooks (Step 4)
Two ranked lists, each sorted by `|z|` descending:

- **Oversold → Reversion (long)**: composite z ≤ −(z cutoff, default 1.0)
  **and** price below the 20-day mean **and** RSI < oversold (default 30).
- **Overbought → Fade (short)**: composite z ≥ +(z cutoff) **and** price above
  the 20-day mean **and** RSI > overbought (default 70).

Each row reports: ticker, name, sector, sub-industry, 1-week z, 1-month-ex-week
z, distance-from-20d-mean, RSI, MACD state, peer-relative z, idiosyncratic tag,
index weight, 20D ADV, and an **event-calendar flag** (warns if a scheduled
earnings/event falls within N days, default 7). Event-flagged rows are
highlighted.

## 5. RSI / MACD definitions
- **RSI(14)** uses **Wilder's smoothing** (recursive moving average, equivalent
  to an EWM with `alpha = 1/length`). Output is bounded [0, 100]; warm-up bars
  are NaN.
- **MACD(12, 26, 9)**: `MACD = EMA12 − EMA26`, `signal = EMA9(MACD)`,
  `hist = MACD − signal`. Columns are normalized to `macd, macd_signal,
  macd_hist`.

The app prefers `pandas_ta` and falls back to a native implementation with
identical semantics; both are unit-tested to agree to < 1e-6 (see
`tests/test_indicators.py`).

## 6. Data hygiene & robustness
- **Min bars** (default 60): names with too few bars for indicator warm-up are
  skipped/flagged rather than producing garbage values.
- FactSet error strings (`#N/A`, `@NA`, `#VALUE!`, …) are scrubbed to NaN and
  counted in the data-quality report.
- Missing data, NaNs, ticker mismatches, and short/stale series never crash the
  screen — they are reported.

## 7. Tuning guidance
- **Vol window** shorter (20d) → more reactive z; longer (60d) → smoother.
- **z cutoff** higher → fewer, more extreme candidates.
- **Divergence threshold** higher → stricter idiosyncratic classification.
- **RSI bounds** can be widened (e.g. 35/65) to surface more names.
- **Event window** controls how aggressively imminent-catalyst names are flagged.

## 8. LLM analysis (optional)
The optional AI layer performs **qualitative synthesis only** — it is explicitly
instructed that RSI/z were computed in-app and that its job is context (likely
driver, reversion-vs-broken, idiosyncratic-vs-sector, risks/catalysts), not to
recalculate signals. It is strictly key-gated and never affects the screen.

- **Per-provider model picker.** Settings exposes a dropdown of the current
  (June 2026) model IDs per provider, sourced from a single `app/llm/models.py`,
  plus an "Other (custom)" escape hatch for arbitrary/forward-compat model IDs.
- **Per-section AI.** Four AI surfaces — per-name notes, portfolio synthesis,
  the results sidebar, and news/catalyst classification — each have an
  independently configurable provider that falls back to the global default.
- **Results sidebar.** The Results page renders a sticky right sidebar that
  AI-synthesizes the *actual* screen rows (most-dislocated names, idiosyncratic
  vs sector split, event/risk flags, top longs/fades). It is generated only on
  an explicit Run Screen / first load after a run and cached per active snapshot
  (not re-called on filter changes). With no key it shows a clean hint and never
  crashes the page; all values come from the screen, never fabricated.

## 9. No-demo-by-default & data provenance
A fresh deployment starts **empty** (no auto-seed). All real data — universe,
price/volume, and the FactSet dictionary — comes from user uploads; the app never
fabricates tickers, prices, or fundamentals in normal operation. A synthetic
sample dataset is available only via the explicit **Load sample/demo data
(synthetic)** button and is clearly labelled as test data. Uploading your own
FactSet dictionary **voids** (deletes) the bundled synthetic demo dictionary so
it can no longer be active or selected.

---

## AI error surfacing, cost estimation & formula metric mapping

- **Error transparency:** httpx providers surface HTTP >=400 bodies (status +
  server message, ~300 chars) instead of discarding them via
  `raise_for_status()`. API keys are `.strip()`-ed to defeat trailing-newline
  auth/400 failures. `base.ping()` returns `{ok, detail, model}` and never
  raises, using a small `max_tokens` (32) and a generous timeout (60s).
- **Cost estimation:** `llm/models.py` holds a `PRICING` table (USD per 1M
  tokens, June-2026 list rates) and `estimate_cost(model, prompt_tokens,
  completion_tokens)`. Token usage is captured per call via
  `provider.last_usage` (OpenAI-style `usage` for Perplexity/DeepSeek;
  `usage.input_tokens/output_tokens` for Anthropic) and logged to `llm_usage`.
  Estimates exclude per-request/search/citation fees; DeepSeek rates are
  approximate/promotional.
- **Configurable formula metrics:** `build_formula_workbook` /
  `method_a_timeseries_formulas` / `method_b_offset_grid` accept
  `price_metric` / `volume_metric` keys, defaulted via
  `formula_gen.autodetect_metrics()` and overridable from the Formula tab so any
  uploaded dictionary's templates are used (not generic P_PRICE/P_VOLUME_DAY).
- **Corrected FQL & rolling window:** generated `=FDS(...)` formulas use the
  correct Excel add-in syntax and a rolling window anchored at today (`0D` =
  today, looking back N trading days). **Default lookback = 150 trading days**
  (≈ 7 months; enough warm-up for RSI/MACD + the 60-day vol window). Re-pull
  anytime to refresh to the latest close.
- **Method A = explicit row-per-day grid:** one self-contained `=FDS` formula
  per trading day for date/close/volume (`P_PRICE(0D)`, `P_PRICE(0D-1D)`, …,
  `P_PRICE(0D-149D)`). This does NOT depend on Excel dynamic-array spill, so a
  full time series always returns regardless of add-in version. (A compact
  single-spill variant still exists for the stacked layout.) Volume uses
  `P_VOLUME_DAY` (not `P_VOLUME`). Method B emits the same per-row offset across
  columns with an explicit-date column. 20-day ADV (USD) is computed in-app
  (Tab 3) from daily price × volume — there is no `P_ADV_USD` field. Universe
  Symbols are used as-is; FactSet resolves SEDOL/exchange-ticker identifiers
  (e.g. `9988-HK`, `BD5CMC`) natively.
  *Troubleshooting no-data:* commas not colons; `P_VOLUME_DAY` not `P_VOLUME`;
  identifier format; `0D`-first order.
