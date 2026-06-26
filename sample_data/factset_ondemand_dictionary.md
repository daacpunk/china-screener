# FactSet OnDemand Field Dictionary — v1.0.0

Derived from the official **FactSet OnDemand – Web Services Reference Manual**
(doc version 2.0.2, FactSet Research Systems Inc.).

> **Read this first — web service vs. Excel `=FDS()`.**
> The source manual documents the FactSet **OnDemand Web Services** (an HTTPS
> API of *Factlets* such as `ExtractDataSnapshot`, `EstimatesOnDemand`,
> `CorporateActionsDividends`). **This app does not call that HTTP API** — it
> generates Excel `=FDS(ticker,"FIELD(...)")` formulas.
>
> The two paths share the same underlying FactSet languages (**FQL** and
> **FSL**): the same **field codes** and the same **date conventions**. So the
> field codes below are **generally usable in `=FDS()` as well, subject to your
> FactSet entitlements**. Each entry is tagged `FDS?` (✓ usable as a field /
> ✗ web-service mechanic only). Where the manual did not give an explicit
> argument signature, the entry says *"verify arg signature / entitlement"*
> rather than guessing.

This dictionary is **additive** — it does not replace the price-series
dictionary used by the Formula Generator. Load whichever you need.

## Syntax & date conventions (from manual §3)

Canonical Excel add-in form:

```
=FDS("IDENTIFIER","ITEM(START_DATE,END_DATE,FREQUENCY)")
```

- **Excel `=FDS()` field form** uses date args **comma-separated INSIDE the
  field's parentheses**, most-recent-first: `P_PRICE(0D,-250D,D)`.
- **Web service form** instead uses a separate `&dates=start:end` **colon**
  argument (e.g. `...&dates=20100101:20100130`). **Do not mix the two.**
- **Relative dates:** `0D` = most recent trading day, `-1D` = one trading day
  prior, `-250D` = 250 trading days back. Frequencies: `D` daily, `W` weekly,
  `M` monthly, plus quarter/year period forms.
- **Absolute dates** (period-end forms from §3.3.1): `MM/YYYY` month-end
  (`6/1999`), `YY/FQ` or `YYYY/FQ` fiscal-quarter-end (`1999/1F`), `YY/CQ`
  calendar-quarter-end (`1999/1C`), `YYYY` fiscal-year-end (`2000`).
- **Estimate horizons** are chosen with **relative fiscal period + period
  type** (`FE_PER_REL`): period `1` + `annual` ⇒ **FY1**, `2` + `annual` ⇒
  FY2, etc.; pair with `FE_FP_END` to get the period-end date.

## Formula index

| Key | Label | Family | FDS? | Template |
|-----|-------|--------|------|----------|
| `price` | Daily closing price | price | ✓ | `P_PRICE({start},{end},{freq})` |
| `volume` | Daily volume | price | ✓ | `P_VOLUME_DAY({start},{end},{freq})` |
| `ff_sales` | Sales / revenue | price | ✓ | `FF_SALES({period})` |
| `ff_eps` | EPS (reported) | price | ✓ | `FF_EPS({period})` |
| `fg_eps` | EPS (global) | price | ✓ | `FG_EPS({asof})` |
| `fg_price` | Price (global) | price | ✓ | `FG_PRICE({asof})` |
| `fe_item` | Estimates item selector (EPS, SALES…) | estimates | ✓ | `FE_ITEM` |
| `fe_per_rel` | Relative fiscal period (FY1/FY2/NTM) | estimates | ✓ | `FE_PER_REL` |
| `fe_fp_end` | Fiscal period end date | estimates | ✓ | `FE_FP_END` |
| `fe_estimate` | Detail estimate (broker-level) | estimates | ✓ | `FE_ESTIMATE` |
| `fe_estimate_value` | Detailed recommendation value | estimates | ✓ | `FE_ESTIMATE_VALUE` |
| `fe_mean` | Consensus mean | estimates | ✓ | `FE_MEAN` |
| `fe_median` | Consensus median | estimates | ✓ | `FE_MEDIAN` |
| `fe_high` | Consensus high | estimates | ✓ | `FE_HIGH` |
| `fe_low` | Consensus low | estimates | ✓ | `FE_LOW` |
| `fe_std_dev` | Consensus std dev | estimates | ✓ | `FE_STD_DEV` |
| `fe_num_est` | Number of estimates | estimates | ✓ | `FE_NUM_EST` |
| `fe_est_rev_val` | Previous estimate value (revisions) | estimates | ✓ | `FE_EST_REV_VAL` |
| `fe_est_rev_val_arrow` | Revision direction (-1/0/1) | estimates | ✓ | `FE_EST_REV_VAL_ARROW` |
| `fe_est_rev_val_date` | Date of previous estimate | estimates | ✓ | `FE_EST_REV_VAL_DATE` |
| `fe_mean_date` | Consensus mean as-of date | estimates | ✓ | `FE_MEAN_DATE` |
| `fe_actual` | Reported actual value | estimates | ✓ | `FE_ACTUAL` |
| `fe_actual_flag` | Actual-available flag | estimates | ✓ | `FE_ACTUAL_FLAG` |
| `fe_report_fy` | Actual report date / FY | estimates | ✓ | `FE_REPORT_FY` |
| `fe_broker` / `fe_brokername` | Broker ID / name | estimates | ✓ | `FE_BROKER` / `FE_BROKERNAME` |
| `fe_analyst` / `fe_analystname` | Analyst ID / name | estimates | ✓ | `FE_ANALYST` / `FE_ANALYSTNAME` |
| `fe_mark` / `fe_mark_text` | Mean recommendation (num / text) | estimates | ✓ | `FE_MARK` / `FE_MARK_TEXT` |
| `fe_buy` `fe_over` `fe_hold` `fe_under` `fe_sell` | Recommendation counts | estimates | ✓ | `FE_BUY` … `FE_SELL` |
| `fe_no_rec` | No-recommendation count | estimates | ✓ | `FE_NO_REC` |
| `fe_total` | Total estimates revised | estimates | ✓ | `FE_TOTAL` |
| `fe_up` `fe_down` `fe_unchanged` | Revision breadth counts | estimates | ✓ | `FE_UP` / `FE_DOWN` / `FE_UNCHANGED` |
| `p_opt_close_price` | Option close | options | ✓ | `P_OPT_CLOSE_PRICE` |
| `p_opt_all_volume` | Option volume | options | ✓ | `P_OPT_ALL_VOLUME` |
| `p_opt_exp_date` | Option expiration | options | ✓ | `P_OPT_EXP_DATEN` |
| `p_opt_delta` | Option delta | options | ✓ | `P_OPT_DELTA` |
| `p_opt_underlying` | Option underlying | options | ✓ | `P_OPT_UNDERLYING_SECURITY` |
| `fds_econ_data` | Economic data item | economic | ✗ | `FDS_ECON_DATA` |
| `endpoint_extract_data_snapshot` | Factlet: ExtractDataSnapshot | reference | ✗ | — |
| `endpoint_extract_formula_history` | Factlet: ExtractFormulaHistory | reference | ✗ | — |
| `endpoint_corporate_actions_dividends` | Factlet: Dividends | corporate_actions | ✗ | — |
| `endpoint_corporate_actions_splits` | Factlet: Splits | corporate_actions | ✗ | — |
| `endpoint_extract_benchmark_detail` | Factlet: BenchmarkDetail | benchmark | ✗ | — |
| `endpoint_extract_screen_universe` | Factlet: ScreenUniverse | reference | ✗ | — |
| `endpoint_extract_vector_formula` | Factlet: VectorFormula | reference | ✗ | — |
| `endpoint_estimates_ondemand` | Factlet: EstimatesOnDemand | estimates | ✗ | — |
| `endpoint_lsd_ownership` | Factlet: LSD_Ownership | ownership | ✗ | — |

## Estimates (§18) — the priority family

Backs the app's **Phase C data generator** (forward EPS, revisions, consensus).

- **Pick the metric** with `FE_ITEM` (e.g. EPS, SALES) and the **horizon** with
  `FE_PER_REL` (relative fiscal period) + period type (annual/quarterly):
  `1`+annual ⇒ **FY1**, `2`+annual ⇒ FY2. `FE_FP_END` returns that period's
  end date.
- **Consensus values:** `FE_MEAN`, `FE_MEDIAN`, `FE_HIGH`, `FE_LOW`,
  `FE_STD_DEV` (dispersion), `FE_NUM_EST` (coverage), with `FE_MEAN_DATE` to
  date the series.
- **Revisions:** compare current `FE_ESTIMATE` against the prior
  `FE_EST_REV_VAL`; `FE_EST_REV_VAL_ARROW` gives the direction
  (−1 down / 0 flat / +1 up) and `FE_EST_REV_VAL_DATE` the prior date.
  Consensus revision breadth: `FE_UP` / `FE_DOWN` / `FE_UNCHANGED` /
  `FE_TOTAL`.
- **Actuals & surprise:** `FE_ACTUAL` (with `FE_ACTUAL_FLAG`, `FE_REPORT_FY`)
  vs. consensus mean gives the surprise.
- **Recommendations:** `FE_MARK` (numeric mean) / `FE_MARK_TEXT` (text, needs
  `meanText=Y`), and the aggregate counts `FE_BUY` / `FE_OVER` / `FE_HOLD` /
  `FE_UNDER` / `FE_SELL` / `FE_NO_REC`.
- **Detail (broker-level):** `FE_ESTIMATE` with `FE_BROKER` / `FE_BROKERNAME`
  / `FE_ANALYST` / `FE_ANALYSTNAME` over a date range.

## Corporate actions (§6–7)

`CorporateActionsDividends` and `CorporateActionsSplits` are **web-service
factlets**. The manual describes their output as report columns (dividend
ex-date / pay date / record date / amount / gross-or-net `G`/`N` marker /
frequency; split date / ratio) rather than discrete `=FDS()` field codes. To
pull these into Excel, **verify the corresponding `P_DIV*` / split field codes
and entitlement** in FactSet. (The app can also flag corporate events from a
user-supplied `event_date` column on the universe upload.)

## Benchmark (§8), Econ (§14), Ownership (§16), Options (§11)

- **Benchmark:** `ExtractBenchmarkDetail` returns constituents + weights; in
  Excel use `FG_INDEX_WEIGHT("<benchmark>",0D)`.
- **Econ:** `FDS_ECON_DATA` via `ExtractEconData` — primarily a web-service
  mechanism; not generally a standard `=FDS()` security field.
- **Ownership:** `LSD_Ownership` factlet (holders data).
- **Options:** `P_OPT_CLOSE_PRICE`, `P_OPT_ALL_VOLUME`, `P_OPT_EXP_DATEN`,
  `P_OPT_DELTA`, `P_OPT_UNDERLYING_SECURITY` — require options entitlement.

## Placeholders

- `{start}` / `{end}` — relative (`0D`, `-250D`) or absolute period-end dates,
  comma-separated, most-recent-first (Excel `=FDS()` form).
- `{freq}` — `D` / `W` / `M` (or quarter/year period forms).
- `{asof}` — single relative/absolute date for point-in-time fields.
- `{period}` — FactSet fiscal-period syntax (e.g. `2024`, `2024/1F`, a relative
  period).

---

*All field codes and descriptions are grounded in the FactSet OnDemand – Web
Services Reference Manual v2.0.2. Availability of any field in the Excel
`=FDS()` add-in depends on your FactSet entitlements; entries whose exact
argument signature was not explicit in the manual are marked "verify arg
signature / entitlement".*
