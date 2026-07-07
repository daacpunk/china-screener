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
| `sector` | FactSet sector (point-in-time) | `FG_FACTSET_SECTOR` |
| `sub_industry` | FactSet industry (point-in-time) | `FG_FACTSET_IND` |
| `index_weight` | Index weight in benchmark (**optional**) | `FG_INDEX_WEIGHT("MSCI CHINA",0D)` |
| `next_earnings` | Next earnings-release date (**optional**, event field) — **=FDSLIVE** | `RTP_EARNINGS_RELEASE_DATE` |
| `earnings_release_status` | Earnings-release status (**optional**, event field) — **=FDSLIVE** | `RTP_EARNINGS_RELEASE_STATUS` |
| `ex_dividend_date` | Ex-dividend date (**optional**, event field) — `=FDS` | `FCA_EVENT_DATE(0,"CASH_DIST","EXDATE","YYYYMMDD")` |

> **Event fields (deterministic MECHANICAL_DISLOCATION tagging).**
> `next_earnings` (`RTP_EARNINGS_RELEASE_DATE`, returns `YYYYMMDD` int e.g.
> `20260831`) and `earnings_release_status` (`RTP_EARNINGS_RELEASE_STATUS`,
> returns text e.g. `"Projected"`/`"Confirmed"`) are LIVE real-time RTP_ fields
> that MUST be pulled with **`=FDSLIVE`** (NOT `=FDS`): e.g.
> `=FDSLIVE(A2,"RTP_EARNINGS_RELEASE_DATE")` and
> `=FDSLIVE(A2,"RTP_EARNINGS_RELEASE_STATUS")`. RTP fields take no date args and
> carry no nested quotes. `ex_dividend_date` (returns `YYYYMMDD`, e.g.
> `20260526`) stays a standard `=FDS` `FCA_EVENT_DATE` pull. All are OPTIONAL
> identity/event columns pulled per ticker in the main-screen template (default
> ON, backward-compatible toggle). They feed the screen engine's event-window
> logic so ex-div / earnings names auto-tag as a mechanical dislocation in the
> research note even without web search; the earnings status is carried through
> as row metadata for the note.
>
> **`FCA_EVENT_DATE` quoting.** Inside `=FDS(...)` the nested string args need
> **doubled** double-quotes, matching how `=FDS` escapes embedded strings:
> ```
> =FDS("9988-HK","FCA_EVENT_DATE(0,""CASH_DIST"",""EXDATE"",""YYYYMMDD"")")
> ```

## Confirmed =FDS fundamentals / estimates / identifiers (authoritative library)

These entries come from the **authoritative, confirmed =FDS formula library**
(see `factset_dictionary.json` / `.md` for the full canonical dictionary incl.
the ~600-keyword estimate item library). They are **added** alongside the
price/volume series formulas above (the price/volume pulls are unchanged) so the
generator can immediately emit confirmed fundamentals/estimates and seed Phase C.

| Key | Label | Family | FQL template |
|-----|-------|--------|--------------|
| `market_cap` | Market capitalization (company, current) | price | `P_MARKET_VAL_CO(USD,1)` |
| `shares_out` | Shares outstanding (company) | fundamentals | `FF_COM_SHS_OUT(ANN,0,,,RF)` |
| `ebitda` | EBITDA (operating) | fundamentals | `FF_EBITDA_OPER(ANN,0,,,RF)` |
| `net_income` | Net income before extraordinaries | fundamentals | `FF_NET_INC(ANN,0,,,RF)` |
| `enterprise_value` | Enterprise value | fundamentals | `FF_ENTRPR_VAL(ANN,0,,,RF)` |
| `fwd_pe_ntm` | Forward P/E (NTM) — native | estimates | `FE_VALUATION(PE,MEAN,NTMA,,0,,,'')` |
| `fy1_eps` | FY1 consensus EPS (mean) | estimates | `FE_ESTIMATE(EPS,MEAN,ANNUAL,+1,0,,,'')` |
| `company_name` | Company name | identifiers | `FG_COMPANY_NAME` |
| `gics_industry` | GICS industry name (reference) | identifiers | `FG_GICS_INDUSTRY` |

> **Notes:** Fundamentals use the `FF_ITEM(ANN,0,,,RF)` template (`0` = most
> recent annual period, `RF` = Report Filing basis flag). Estimate nest strings
> use **single quotes** (e.g. `''`). The verified-working classification fields
> for this entitlement are `FG_FACTSET_SECTOR` / `FG_FACTSET_IND` (GICS variants
> returned no data; `FG_GICS_INDUSTRY` kept for reference). The live **weekly**
> template keeps its user-tested `ANN_ROLL`/`NOW` estimate form; the `fy1_eps`
> entry here documents the authoritative `ANNUAL`/`0` reference form.

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
