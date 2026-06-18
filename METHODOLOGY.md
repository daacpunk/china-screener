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
