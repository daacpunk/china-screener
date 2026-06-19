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

### Volatility-normalized z-score (RAW by default in v2)
Daily-return mean `μ` and volatility `σ` are estimated over a trailing window
(default **60** trading days, configurable 20–60). The horizon return is
standardized and scaled to the horizon length `h` by `√h`. As of **v2 the
default is RAW** (no drift subtraction), so a genuinely trending name is not
pulled toward zero by its own positive/negative drift:

```
z = r_horizon / (σ_daily · √h)               # RAW (default, demean = False)
z = (r_horizon − μ_daily · h) / (σ_daily · √h)  # demeaned (legacy, demean = True)
```

The `demean` toggle (default **OFF**) restores the legacy drift-subtracted form.

**Ranking z (`rank_z`).** Instead of a fixed 50/50 composite, v2 derives a
signed `rank_z` per the `rank_mode` parameter:
- **`max_abs`** (default): the horizon (1-week `z_a` or 1-month-ex-week `z_b`)
  with the larger magnitude, **sign preserved**. If one horizon is missing, the
  other is used; if both are missing, `rank_z` is NaN. This stops a violent
  1-week move from being halved by a quiet prior month.
- **`weighted`**: a weighted blend of `z_a`/`z_b` (renormalizing when one is
  NaN); `composite_z` is reported.
- **`horizon_a`**: `z_a` only (`z_b` is a confirmation column).

Both `z_1w` and `z_1m_ex_week` columns stay visible in every mode. The master
and both playbooks rank by **`|rank_z|`** descending — the goal is to surface
the extremes in both tails, not to rank toward the median.

### Reversion metrics
- **Distance from 20-day mean**: `(P − SMA20) / SMA20`, also expressed in σ
  units (`dist / σ_daily`).
- **RSI(14)** — Wilder's RSI (see §5).
- **MACD(12, 26, 9)** — state is *Bullish* if MACD line > signal line, else
  *Bearish*.

## 3. Idiosyncratic vs sector (Step 3) — leave-one-out + roll-up + solo
For each name we compare its `rank_z` to a **leave-one-out** peer median that
**excludes the name itself** (so a name can't anchor its own peer group). The
group is chosen by availability, controlled by `min_peers` (default 3):

1. **Sub-industry**: if the GICS sub-industry has ≥ `min_peers` OTHER names, use
   their median `rank_z` (`peer_group_used = "sub_industry"`).
2. **Sector roll-up**: else if the GICS sector has ≥ `min_peers` OTHER names, use
   their median (`peer_group_used = "sector"`).
3. **Solo**: else there is no group to net against; the name is tagged
   **IDIOSYNCRATIC** outright (`peer_group_used = "solo"`, `peer_count = 0`).

```
peer_relative_z = rank_z − leave_one_out_peer_median_rank_z   (when a group is used)
IDIOSYNCRATIC  if  |peer_relative_z| ≥ divergence_threshold (default 1.0)  OR  solo
otherwise      ⇒  SECTOR / MACRO / POLICY
```

Output columns include `peer_relative_z`, `peer_group_used`, and `peer_count`.
This separates single-name dislocations from sector- or macro-wide moves and is
robust to thin or singleton sub-industries.

## 4. Playbooks (Step 4) — scored by default, strict-AND opt-in
Two ranked lists. **RSI bands default to 35 / 65** (was 30 / 70). The
`playbook_mode` parameter selects the membership rule:

**Scored mode (default).** Each name gets a normalized 0..1-ish score built from
normalized magnitudes, documented and configurable via weights:

```
reversion_score = w_z·|rank_z|down + w_dist·|dist_sigma|down + w_rsi·(RSI below oversold) + MACD-bearish bonus
fade_score      = w_z·|rank_z|up   + w_dist·|dist_sigma|up   + w_rsi·(RSI above overbought) + MACD-bullish bonus
```

(default weights `w_z = 0.5`, `w_dist = 0.3`, `w_rsi = 0.2`, `macd_bonus = 0.1`;
only the downside/upside magnitude contributes to each). A name enters:
- **Oversold → Reversion (long)**: `rank_z < 0` **and** `reversion_score ≥
  score_threshold` (default 0.5) — ranked by `reversion_score` desc.
- **Overbought → Fade (short)**: `rank_z > 0` **and** `fade_score ≥
  score_threshold` — ranked by `fade_score` desc.

**Strict mode (opt-in).** The legacy hard AND, ranked by `|rank_z|` desc:
- Oversold: `rank_z ≤ −(z cutoff, default 1.0)` **and** price below the 20-day
  mean **and** RSI < oversold.
- Overbought: symmetric.

**Both horizons required.** A name is only eligible for either playbook when
both `z_a` and `z_b` are present (`partial_history == False`) — a 5-day-only z
can't sneak into a playbook unflagged (see §6).

Each row reports: ticker, name, sector, sub-industry, 1-week z, 1-month-ex-week
z, `rank_z`, the kind-appropriate score, distance-from-20d-mean, RSI, MACD
state, peer-relative z, `peer_group_used`/`peer_count`, idiosyncratic tag,
`partial_history` / `adv_unknown` flags, index weight, 20D ADV, and an
**event-calendar flag** (warns if a scheduled earnings/event falls within N
days, default 7). Event-flagged rows are highlighted.

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
- **Partial history** (v2): a name missing either horizon z (`z_a` or `z_b`
  NaN) is tagged `partial_history = True`. It **stays in the master** (nothing
  is hidden) but is **excluded from the playbooks** so an incomplete signal
  can't rank high unflagged. Surfaced as a small badge.
- **Unknown-ADV policy** (v2, `unknown_adv_policy`): names whose 20D ADV is
  blank/NaN get `adv_unknown = True`. `"flag"` (default) keeps them screenable
  with a badge; `"exclude"` moves them to the skipped list; `"include"` keeps
  them silently (the flag is still set for transparency). This is separate from
  the hard liquidity floor (`below_floor = adv.notna() & adv < floor`).
- **As-of stamp & staleness** (v2): the result carries `asof` (max price date).
  The Results and Data tabs show "Data as of {asof} ({n} business days ago)" and
  raise a warning banner when older than `staleness_days` (default 3) —
  "re-pull FactSet before trading."
- **Event overlay** (v2): an optional `event_date` column (tolerant aliases:
  `event_date`, `next_earnings`, `earnings_date`, `next_event`, `fe_rep_dt_next`,
  `report_date`) feeds the catalyst flag. If no name has a usable event date,
  `event_data_loaded` is False, the Results note says the calendar isn't loaded,
  and the hide-imminent-event toggle is disabled. The formula generator can emit
  an optional `=FDS(A2,"FE_REP_DT_NEXT(0)")` next-event column (toggle, default
  off).
- FactSet error strings (`#N/A`, `@NA`, `#VALUE!`, …) are scrubbed to NaN and
  counted in the data-quality report.
- Missing data, NaNs, ticker mismatches, and short/stale series never crash the
  screen — they are reported.

## 7. Tuning guidance
- **Vol window** shorter (20d) → more reactive z; longer (60d) → smoother.
- **z cutoff** higher → fewer, more extreme candidates.
- **Divergence threshold** higher → stricter idiosyncratic classification.
- **RSI bounds** default to 35/65 in v2; tighten to 30/70 for a more selective
  list.
- **rank_mode** picks how the two horizons combine (`max_abs` default).
- **playbook_mode** switches scored (default) vs strict hard-AND membership;
  **score_threshold** tunes how selective the scored lists are.
- **min_peers** controls when peer classification rolls sub-industry up to sector
  or falls back to solo/idiosyncratic.
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
- **Method A default = SPILLING per-ticker layout (fast):** the user's FactSet
  add-in supports dynamic-array spill, so each ticker gets its OWN sheet with the
  ticker literal in `A2` and a SINGLE spilling range formula per series —
  `=FDS("9988-HK","P_PRICE(0D,-109D,D)")` (close) and
  `=FDS("9988-HK","P_VOLUME_DAY(0D,-109D,D)")` (volume), comma range form,
  most-recent-first. The add-in fills the whole column, so a 576-name pull drops
  from ~125k per-cell calls to ~1,150 (~2 calls/ticker). The date axis spills in
  column B as `P_DATE(0D,-Nd,D)` only when *Include date column* is on (best-
  effort; if `P_DATE` is blank, leave it off — dates are reconstructed in-app from
  row order). FQL roots come from the active dictionary's templates (via
  `_fql_root`) so custom dictionaries work. `build_formula_workbook(layout="spill")`
  is the default; `method_a_spill_formulas()` builds the per-ticker formulas.
- **Batching for large universes:** `build_formula_workbooks_batched(tickers, …,
  batch_size)` splits the universe into chunks (default 75/file) and returns a
  list of `(filename, bytes)`; the `/formula/download` route zips them with
  stdlib `zipfile` into `factset_formulas_method_A.zip` when the universe exceeds
  the batch size. Each file is a standalone workbook whose Instructions sheet
  notes `Batch k of M — tickers X..Y`; 576 names → 8 files at the default size.
  `_strip_empty_formula_values` runs on EVERY generated workbook (including each
  batched one) so Excel never shows the “problem with content” repair prompt.
- **Fallback layouts (no spill):** `layout="per_ticker"` writes the explicit
  row-per-day grid (`P_PRICE(0D)`, `P_PRICE(0D-1D)`, …, `P_PRICE(0D-149D)`) — a
  full series always returns regardless of add-in version; `layout="stacked"`
  emits a single tidy-long `AllTickers` sheet. Volume uses `P_VOLUME_DAY` (not
  `P_VOLUME`). Method B emits the same per-row offset across columns with an
  explicit-date column. 20-day ADV (USD) is computed in-app (Tab 3) from daily
  price × volume — there is no `P_ADV_USD` field. Universe Symbols are used
  as-is; FactSet resolves SEDOL/exchange-ticker identifiers (e.g. `9988-HK`,
  `BD5CMC`) natively.
- **Upload of spilled sheets:** Tab 3 `parse_prices` forward-fills the ticker
  column when a spill per-ticker sheet is uploaded directly (ticker only in `A2`,
  blank below, while close/volume fill down), without breaking the existing tidy
  path or the date-reconstruction / all-NaT fallbacks.
  *Troubleshooting no-data:* commas not colons; `P_VOLUME_DAY` not `P_VOLUME`;
  identifier format; `0D`-first order; ensure spill isn't blocked.
