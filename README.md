# MSCI China Reversion / Fade Equity Screener

A production-ready, Railway-deployable FastAPI web app that screens an equity
universe (MSCI China + manual additions) for **statistically stretched** names
and produces two ranked trade lists:

- **Oversold → Reversion (longs)** — buy-the-dip candidates
- **Overbought → Fade (shorts)** — sell-the-rip candidates

The app **ingests user-uploaded FactSet price/volume data and makes NO
market-data API calls.** It computes RSI, MACD, volatility-normalized z-scores,
distance-from-20-day-mean, and peer-relative (idiosyncratic-vs-sector) metrics
itself in Python.

---

## Quick start (local)

```bash
cd screener
python -m venv .venv && source .venv/bin/activate     # optional
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000
```

A fresh database starts **empty** — there is no auto-seed. Every tab renders a
clean empty state pointing you to upload real FactSet data. To explore the app
without FactSet/API keys, press **Load sample/demo data (synthetic)** in
Settings; this loads clearly-labelled *synthetic test data* (not market data).

### Try the app end-to-end (no FactSet, no API keys)
1. Open the app → **Settings** → **Load sample/demo data (synthetic)**.
2. Go to **Data & Indicators** → **▶ Run Screen** (or just open **Results**).
3. You'll see populated **Oversold-Reversion** and **Overbought-Fade** tables,
   a master "most dislocated by |z|" view, and an idiosyncratic-vs-sector tag.

### Run the tests
```bash
cd screener
python -m pytest -q
```

---

## The five tabs

| # | Tab | What it does |
|---|-----|--------------|
| 1 | **Universe** | Upload constituents (CSV/XLSX, tolerant column mapping), version them, add manual tickers, apply a liquidity floor (default 20D ADV > $10m). Below-floor names are kept in a separate view, never deleted. |
| 2 | **Formula Generator** | Generates FactSet `=FDS(...)` price-series formulas from the active FQL dictionary. Method A (time-series block) or Method B (offset grid). Bulk-download to `.xlsx`. Indicators are **not** pulled — they're computed in Tab 3. |
| 3 | **Data & Indicators** | Upload completed FactSet price/volume data (tidy or wide). Data-quality report (missing tickers, NaNs, short series, FactSet error strings). Computes RSI/MACD per name. **Run Screen** button. |
| 4 | **Results** | Two ranked tables + master view. Filters (sector, sub-industry, idiosyncratic-only, hide-event, RSI bounds, MACD state). Excel export. Two-column layout with a sticky **AI synthesis sidebar** (auto-populated on Run Screen, key-gated, cached per snapshot, responsive). Optional inline AI analysis. |
| 5 | **Settings (Admin)** | Dictionary versioning + validation (uploading your own dictionary **voids** the synthetic demo dictionary); encrypted API keys with a **per-provider model dropdown** (current June-2026 models + custom escape hatch); **per-section AI selector** (per-name / portfolio / sidebar / news, each falling back to the global default provider); screen parameters with reset-to-default; explicit synthetic sample-data loader. |

---

## Environment variables

Copy `.env.example` → `.env` (all optional — the app runs with none; AI features stay disabled until a key is set).

| Var | Default | Purpose |
|-----|---------|---------|
| `DB_PATH` | `/data/app.db` | SQLite path. Falls back to `./app.db` if `/data` is not writable. |
| `APP_SECRET` | (derived) | Master secret used to derive the Fernet key for API-key encryption. Set a strong random value in production. |
| `PORT` | `8000` | Railway injects `$PORT` automatically. |
| `PERPLEXITY_API_KEY` | — | Optional. Enables Perplexity Sonar analysis. Overrides stored key. |
| `ANTHROPIC_API_KEY` | — | Optional. Enables Claude analysis. |
| `DEEPSEEK_API_KEY` | — | Optional. Enables DeepSeek analysis. |

Env vars always take precedence over the encrypted SQLite store.

---

## Deploying to Railway

1. Push this repo to GitHub and create a Railway project from it.
2. Railway detects **Nixpacks** (`nixpacks.toml`, `railway.json`). Build runs
   `pip install -r requirements.txt`; start runs
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. **Add a Volume** mounted at **`/data`** so the SQLite DB (universes,
   dictionaries, snapshots, settings, encrypted keys) survives restarts.
   Keep `DB_PATH=/data/app.db` (the default).
4. Set `APP_SECRET` to a strong random value (e.g.
   `python -c "import secrets;print(secrets.token_urlsafe(48))"`).
5. Optionally set provider API keys as service variables.

`Procfile`, `railway.json`, and `nixpacks.toml` are all included and `$PORT`-aware.

---

## File schemas

### Universe upload (Tab 1) — CSV/XLSX, tolerant headers
Expected columns (case/spacing-insensitive; fuzzy-matched):
`Ticker, Name, Sector, Sub-Industry, Index Weight, [20D_ADV_USD]`.

### Price/volume upload (Tab 3)
**Tidy (preferred):** `ticker, date, close, volume` (price aliases accepted:
`close / price / p_price / adj close`). **Wide:** first column = dates, each
remaining column = a ticker's close. FactSet error strings (`#N/A`, `@NA`,
`#VALUE!`, …) are scrubbed and reported.

### FactSet dictionary (Tab 5)
JSON object with a `formulas` map; each entry must have an `fql_template`:
```json
{ "formulas": { "price": { "fql_template": "P_PRICE({start},{end},{freq})" } } }
```
Date args are **comma-separated inside the field's parentheses**, most-recent-first
(e.g. `P_PRICE(0D,-250D,D)`). An optional Markdown wiki renders as docs. Malformed
uploads are rejected and the prior active version is preserved.

---

## Settings & key management
- **Dictionary versions**: every upload is timestamped; activate any version;
  Tabs 2–3 consume the active one. Upload shows an added/removed metric-key diff.
- **API keys**: masked (last 4 chars), never logged, encrypted at rest with
  Fernet derived from `APP_SECRET`. Env vars override the store. Per-provider
  model, enable toggle, and a lightweight **Test connection** ping.
- **Screen parameters**: z cutoff, RSI bounds, MACD params, lookbacks, vol
  window, divergence threshold, event window, ADV floor — all editable with
  reset-to-default.

---

## Worked example (demo data)
The synthetic 250-day series is engineered so that, with default parameters:

- **BABA-CN** and **BIDU-CN** show sharp recent drops (RSI ≈ 13–15, large
  negative z) and are tagged **IDIOSYNCRATIC** vs their sub-industry peers.
- **PDD-CN** and **CATL-CN** show sharp rallies (RSI ≈ 87–90, large positive z)
  and surface in the overbought-fade list.
- **NANO-CN** is below the liquidity floor and is excluded but retained.

Run Screen returns ~5 oversold longs and ~2 overbought shorts, each ranked by
`|z|`.

---

## Indicator backend
The app prefers **`pandas_ta==0.4.71b0`** for RSI/MACD and transparently falls
back to a **native NumPy/pandas Wilder/EMA implementation** with identical
output column names (`rsi, macd, macd_signal, macd_hist`) if pandas_ta is
unavailable. Both paths are unit-tested to agree to < 1e-6. The active backend
is shown on the Data & Indicators tab. See `BUILD_NOTES.md` for the rationale.

> **Disclaimer:** Educational tool. Not investment advice.

---

## AI provider error surfacing, key caveats & cost audit

**Improved "Test connection" errors.** The httpx providers (Perplexity,
DeepSeek) no longer hide error bodies behind `raise_for_status()`. On any
HTTP status >= 400 they now read the JSON/text response body and raise an
`LLMError` that includes the status code AND the server's message (truncated
to ~300 chars). A Perplexity 400/401 now surfaces as, for example:

```
Perplexity 401: {'error': {'message': 'Invalid API key provided. ...', 'type': 'invalid_api_key', 'code': 401}}
Perplexity 400: {'error': {'type': 'invalid_model', 'message': '...'}}
```

**Common 400/401 causes:** a **trailing newline in a pasted API key** (now
stripped automatically via `.strip()` in `LLMProvider.__init__`) and a **stale
or mistyped model id**. The Settings → Test connection result shows the model
tested plus the full surfaced error so the cause is visible.

**Cost / usage audit.** Every AI call (sidebar synthesis, per-name notes,
portfolio synthesis, news classification, and connection pings) is logged to a
lightweight `llm_usage` ledger with token counts and an estimated USD cost.
The **Settings → AI usage & cost audit** panel shows totals, a per
provider/model/section breakdown, a recent-calls table, and a Reset button.
Estimates are **token-based at list prices and EXCLUDE per-request/search fees**
(notably Perplexity request fees and Sonar Deep Research citation/reasoning
fees); DeepSeek rates are approximate/promotional. Actual billing may differ.

## Formula Generator — configurable price/volume metric mapping

The Formula tab shows the full list of metric keys in your active dictionary
and lets you pick which key represents **price** and which represents **volume**
via two dropdowns (auto-detected with smart defaults: a key containing
price/close/px for price, volume/vol for volume). These selections thread
through both the single-formula preview and the bulk `.xlsx` export, so a
dictionary that names its series `px_last` / `vol` is honoured instead of
falling back to the generic `P_PRICE` / `P_VOLUME_DAY` templates.

## FactSet pull — corrected FQL & rolling-from-today window

The generated `=FDS(...)` formulas use the **correct Excel add-in syntax** and a
**rolling window anchored at today**: `0D` = today / most-recent trading day,
looking back N trading days. Re-pull anytime to refresh to the latest close.

**Efficient by default (important for ~500+ name universes):**
- **Auto lookback depth** — leave the Lookback field blank and the app sizes the
  pull to the *minimum contiguous depth the screen actually needs* (computed from
  the current screen params: MACD 26+9, RSI 14, 60-day vol window, 21-day
  horizon, +25% buffer — ≈ **109 trading days** at defaults). Override to pull more.
  Indicators are consecutive-day calcs, so depth (not sparsity) is what matters.
- **Date column off by default** — the grid pulls only **close + volume**
  (≈ 1/3 fewer FDS cells). Dates are reconstructed in-app from row order
  (row 1 = latest trading day). Tick "Include date column" to pull `P_DATE` too.
- Combined, this is ~**50% fewer FactSet cells** for a 576-name universe
  (≈ 126k vs ≈ 259k cells) vs the old 150-day × 3-column pull.

**Method A (recommended) writes an explicit row-per-day grid** — one
self-contained `=FDS` formula PER trading day for date / close / volume. This does
**not** rely on Excel dynamic-array spill, so a full time series always returns
(one value per row) on any FactSet add-in version:

- Row 2 (today): `=FDS("9988-HK","P_PRICE(0D)")`, `=FDS("9988-HK","P_VOLUME_DAY(0D)")`
- Row 3: `=FDS("9988-HK","P_PRICE(0D-1D)")` … down to `0D-149D`
- Date column: `=FDS("9988-HK","P_DATE(0D-N D)")` (best-effort; if `P_DATE` is not
  in your entitlement, dates follow from the row offset — row 2 = latest day)
- Use **`P_VOLUME_DAY`**, not `P_VOLUME`.
- Method B (offset grid, also explicit): `=FDS($A$2,"P_PRICE(0D-"&(ROW()-3)&"D)")`
  and `=FDS($A$2,"P_VOLUME_DAY(0D-"&(ROW()-3)&"D)")`, plus an explicit-date column.
- **20-day ADV (USD) is computed in-app** (Tab 3) from daily price × volume —
  there is no `P_ADV_USD` field.
- Identifiers (e.g. `9988-HK`, `2883-HK`, `BD5CMC`, `BP3R5S`) are used **as-is**;
  FactSet resolves SEDOL / exchange-ticker identifiers natively — do not mangle them.

**Troubleshooting (no data):** (a) commas not colons inside the field,
(b) `P_VOLUME_DAY` not `P_VOLUME`, (c) identifier format (e.g. `9988-HK`, `BD5CMC`),
(d) `0D`-first (most-recent-first) order.
