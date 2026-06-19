# FactSet FQL Price-Series Dictionary (sample) — v2.0.0

This wiki documents the **corrected** FQL formulas used by the **Formula
Generator (Tab 2)** to pull clean daily price/volume time series and
point-in-time reference data out of FactSet via the Excel `=FDS(...)` function.

> **Indicators (RSI, MACD, z-scores) are NOT pulled from FactSet.** They are
> computed inside this app (Tab 3) from the uploaded price/volume series.
> **20-day ADV (USD) is also computed in-app** from daily price × volume.

## Correct FQL syntax (verified against FactSet docs)

Canonical Excel add-in form:

```
=FDS("IDENTIFIER","ITEM(START_DATE,END_DATE,FREQUENCY)")
```

- Date args are **COMMA-separated INSIDE the field's parentheses** — **not** a
  colon `start:end:freq` string (that colon form is the OnDemand web-service
  `dates` argument, not the Excel field syntax).
- **Most-recent-first** order: `START=0D` (today / most-recent trading day),
  `END=-250D` (lookback), `FREQUENCY=D` (daily). e.g. `P_PRICE(0D,-250D,D)`.
- Relative dates: `0D` = most recent trading day, `-1D` = one trading day prior,
  `-250D` = 250 trading days back.
- Single point-in-time: `P_PRICE(0D)` returns the latest close.
- Volume field is **`P_VOLUME_DAY`** (preferred; `P_VOLUME` is the legacy name).

## Formula index

| Key | Label | FQL template |
|-----|-------|--------------|
| `price` | Daily closing price | `P_PRICE({start},{end},{freq})` |
| `volume` | Daily volume | `P_VOLUME_DAY({start},{end},{freq})` |
| `price_point` | Closing price (single date / spot) | `P_PRICE({asof})` |
| `volume_point` | Volume (single date / spot) | `P_VOLUME_DAY({asof})` |
| `date_point` | Trading date (best-effort) | `P_DATE({asof})` |
| `adv_usd_20d` | 20-day avg daily value traded (USD) — **optional, computed in-app** | `AVG(P_PRICE(0D,-19D,D)*P_VOLUME_DAY(0D,-19D,D))` |
| `sector` | GICS sector (point-in-time) | `FG_GICS_SECTOR` |
| `sub_industry` | GICS sub-industry (point-in-time) | `FG_GICS_SUB_IND` |
| `index_weight` | Index weight in benchmark (**optional**) | `FG_INDEX_WEIGHT("MSCI CHINA",0D)` |
| `next_earnings` | Next earnings/report date (**optional**) | `FE_REP_DT_NEXT(0D)` |

## Placeholders

- `{start}` / `{end}` — relative (`0D`, `-250D`) or explicit dates (`20240101`),
  comma-separated, most-recent-first.
- `{freq}` — `D` daily (used throughout this screen).
- `{asof}` — a single relative/explicit date for point-in-time fields.

## Rolling-from-today window (default)

The default pull is a **rolling window anchored at today**:
`start = 0D` (today / most-recent trading day), `end = -250D`
(≈ 250 trading days ≈ ~1Y of trading, comfortably more than RSI(14) + z-score
windows), `freq = D`. **Re-pull anytime to refresh to the latest close.**

## Method A — time-series block (preferred)

A single spilling FDS formula per series using the comma range form:

```
=FDS("9988-HK","P_PRICE(0D,-250D,D)")       -> spills ~250 daily closes
=FDS("9988-HK","P_VOLUME_DAY(0D,-250D,D)")  -> spills daily volume
```

FactSet provides the date column automatically alongside the price spill.

## Method B — offset grid (fallback, bullet-proof)

One row per trading day, each a self-contained single-date formula using the
`0D-Nd` offset (today minus N trading days), so row 1 = today and rows go back:

```
price  : =FDS($A$2,"P_PRICE(0D-"&(ROW()-2)&"D)")
volume : =FDS($A$2,"P_VOLUME_DAY(0D-"&(ROW()-2)&"D)")
explicit date in col B variant: =FDS($A$2,"P_PRICE("&B2&")")
```

## Identifiers (A-share / SEDOL)

`=FDS` accepts universe identifiers directly — e.g. `9988-HK`, `2883-HK`,
`BD5CMC`, `BP3R5S`. The generator uses the universe's Symbol **as-is**; FactSet
resolves SEDOL / exchange-ticker identifiers natively. **Do not mangle them.**

## Troubleshooting — if FactSet returns no data

- (a) Use **commas, not colons** inside the field, e.g. `P_PRICE(0D,-250D,D)`.
- (b) Use **`P_VOLUME_DAY`**, not `P_VOLUME`.
- (c) Check the **identifier format**, e.g. `9988-HK`, `BD5CMC`.
- (d) Use **`0D`-first** (most-recent-first) order.
