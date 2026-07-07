# FactSet =FDS Formula Dictionary — v3.0.0

This wiki is the **canonical** FactSet `=FDS` Excel formula reference for this app. It is built from the **AUTHORITATIVE, confirmed =FDS formula library** and **supersedes** the prior OnDemand-manual dictionary (which carried wrong field names). It backs the **Formula Generator (Tab 2)**, the **Weekly Note**, and **Phase C** estimate prep.

**Compiled from:**

- =FDS Formulas Quick Reference (FactSet, 2014)
- Online Assistant p.16114 - FE_ESTIMATE
- Online Assistant p.20420 - Changing the Report Layout
- FactSet Estimates Items & Keywords (spreadsheet, 20 Apr 2026)

## Syntax conventions

**Base structure:**

```
=FDS(symbol_or_cell, "FORMULA_CODE(arguments)")
```

**Placeholders:**

| Token | Meaning |
|-------|---------|
| `SD` | start date |
| `ED` | end date |
| `FRQ` | frequency |
| `0` | most recent / current period (negative offsets go back in time) |
| `RF` | Report Filing basis flag (fundamentals) |
| `ANN` | annual periodicity (substitutable) |
| `CONTEXT` | estimate context arg (brokers / methodology) |

**Quote escaping:**

- Price & fundamentals: nested strings use doubled double-quotes, e.g. ""DATEJ""
- Estimates: nested strings use single quotes, e.g. 'MM/DD/YYYY' or ''

**Syntax-mode conversions:**

- `fql_downloading`: prefix code with ^=
- `universal_screening`: drop sdate/edate/frq, use single 'date' arg
- `screening_downloading`: prefix universal-screening form with ^%

## Formula index — Price

| Key | Label | Family | FQL template |
|-----|-------|--------|--------------|
| `price` | Closing price (single date / spot) | price | `P_PRICE(0)` |
| `price_range` | Price over date range | price | `P_PRICE({SD},{ED},{FRQ})` |
| `price_range_ccy` | Price over range with currency | price | `P_PRICE({SD},{ED},{FRQ},{CURRENCY})` |
| `price_high_52w` | 52-week high | price | `P_PRICE_HIGH_52W(0)` |
| `price_low_52w` | 52-week low | price | `P_PRICE_LOW_52W(0)` |
| `price_change` | Price change between dates | price | `P_PRICE_CHANGE({SD},{ED})` |
| `total_return` | Compounded total return (ExDate reinvest) | price | `P_TOTAL_RETURNC({SD},{ED})` |
| `volume_cum` | Cumulative volume between dates | price | `P_VOLUME({SD},{ED})` |
| `exch_rate` | Exchange rate | price | `P_EXCH_RATE(EUR,USD,0)` |
| `market_cap` | Market capitalization (company, current) | price | `P_MARKET_VAL_CO({CURRENCY},1)` |
| `currency` | Currency (local name) | price | `P_CURRENCY` |
| `date_eu` | Date (European format) | price | `P_DATEIC_DAY(0)` |

## Formula index — Fundamentals

| Key | Label | Family | FQL template |
|-----|-------|--------|--------------|
| `ff_com_shs_out` | Shares Outstanding - Company | fundamentals | `FF_COM_SHS_OUT(ANN,0,,,RF)` |
| `ff_com_shs_out_secs` | Shares Outstanding - Security | fundamentals | `FF_COM_SHS_OUT_SECS(ANN,0,,,RF)` |
| `ff_mkt_val` | Market Value (period-end price) | fundamentals | `FF_MKT_VAL(ANN,0,,,RF)` |
| `ff_entrpr_val` | Enterprise Value (equity value) | fundamentals | `FF_ENTRPR_VAL(ANN,0,,,RF)` |
| `ff_sales` | Net Sales | fundamentals | `FF_SALES(ANN,0,,,RF)` |
| `ff_ebit_oper` | EBIT | fundamentals | `FF_EBIT_OPER(ANN,0,,,RF)` |
| `ff_ebitda_oper` | EBITDA | fundamentals | `FF_EBITDA_OPER(ANN,0,,,RF)` |
| `ff_div_com_cf` | Dividends - Total | fundamentals | `FF_DIV_COM_CF(ANN,0,,,RF)` |
| `ff_gross_inc` | Gross Income | fundamentals | `FF_GROSS_INC(ANN,0,,,RF)` |
| `ff_oper_inc` | Operating Income | fundamentals | `FF_OPER_INC(ANN,0,,,RF)` |
| `ff_net_inc` | Net Income before Extraordinaries | fundamentals | `FF_NET_INC(ANN,0,,,RF)` |
| `ff_int_exp_debt` | Interest Expense | fundamentals | `FF_INT_EXP_DEBT(ANN,0,,,RF)` |
| `ff_cash_st` | Cash & Equivalents | fundamentals | `FF_CASH_ST(ANN,0,,,RF)` |
| `ff_assets` | Assets - Total | fundamentals | `FF_ASSETS(ANN,0,,,RF)` |
| `ff_debt_st` | Short-term Debt | fundamentals | `FF_DEBT_ST(ANN,0,,,RF)` |
| `ff_debt_lt` | Long-term Debt | fundamentals | `FF_DEBT_LT(ANN,0,,,RF)` |
| `ff_debt` | Debt - Total | fundamentals | `FF_DEBT(ANN,0,,,RF)` |
| `ff_liabs` | Liabilities - Total | fundamentals | `FF_LIABS(ANN,0,,,RF)` |

_Fundamentals template_: `FF_ITEM(ANN,0,,,RF)`. Periodicity options: `ANN, QTR, SEMI, LTM, LTM_SEMI, YTD, CAL`. `RF` = Report Filing basis flag; `0` = most recent period (negative offsets go back in time). Date companion: `FF_FISCAL_DATE(ANN,0,,,RF,"DATEJ")`.

## Formula index — Estimates

| Key | Label | Family | FQL template |
|-----|-------|--------|--------------|
| `fe_estimate` | Consensus estimate (FE_ESTIMATE function) | estimates | `FE_ESTIMATE({item},{statistic},{report_basis},{period},0,,,'')` |
| `fe_actual` | Reported actual (FE_ACTUAL function) | estimates | `FE_ACTUAL(ACTUAL,{item},{report_basis},{period},,,,'')` |
| `fe_valuation_pe_ntm` | Forward P/E — NTM (FE_VALUATION, native) | estimates | `FE_VALUATION(PE,MEAN,NTMA,,0,,,'')` |
| `fe_valuation_pe_fy1` | Forward P/E — FY1 (FE_VALUATION, native) | estimates | `FE_VALUATION(PE,MEAN,ANNUAL,+1,0,,,'')` |
| `est_fy1_eps_mean` | FY1 Mean EPS (prebuilt FE_ESTIMATE template) | estimates | `FE_ESTIMATE(EPS,MEAN,ANNUAL,+1,0,,,'')` |
| `est_fy1_eps_mean_roll` | FY1 Mean EPS - Rolling (prebuilt FE_ESTIMATE template) | estimates | `FE_ESTIMATE(EPS,MEAN,ANNUAL_ROLL,+1,0,,,'')` |
| `est_fy2_eps_mean_roll` | FY2 Mean EPS - Rolling (prebuilt FE_ESTIMATE template) | estimates | `FE_ESTIMATE(EPS,MEAN,ANNUAL_ROLL,+2,0,,,'')` |
| `est_fq1_eps_mean_roll` | FQ1 Mean EPS - Rolling (prebuilt FE_ESTIMATE template) | estimates | `FE_ESTIMATE(EPS,MEAN,QUARTERLY_ROLL,+1,0,,,'')` |
| `est_fy1_sales_mean_roll` | FY1 Mean Sales - Rolling (prebuilt FE_ESTIMATE template) | estimates | `FE_ESTIMATE(SALES,MEAN,ANNUAL_ROLL,+1,0,,,'')` |
| `est_ntm_eps_mean` | NTM EPS - Rolling (prebuilt FE_ESTIMATE template) | estimates | `FE_ESTIMATE(EPS,MEAN,NTMA,,0,,,'')` |
| `est_ltg_mean` | Long-Term Growth Mean (prebuilt FE_ESTIMATE template) | estimates | `FE_ESTIMATE(EPS_LTG,MEAN,,,0,,,'')` |
| `est_cal_eps_mean` | Calendarized EPS (prebuilt FE_ESTIMATE template) | estimates | `FE_ESTIMATE(EPS,MEAN,CALA,1CY,0,,,'')` |

## Formula index — Identifiers

| Key | Label | Family | FQL template |
|-----|-------|--------|--------------|
| `company_name` | Company name | identifiers | `FG_COMPANY_NAME` |
| `exchange` | Exchange | identifiers | `FG_EXCHANGE` |
| `gics_industry` | GICS industry name (reference) | identifiers | `FG_GICS_INDUSTRY` |
| `factset_sector` | FactSet sector (verified classification) | identifiers | `FG_FACTSET_SECTOR` |
| `factset_industry` | FactSet industry (verified classification) | identifiers | `FG_FACTSET_IND` |

> **Classification note:** `FG_FACTSET_SECTOR` / `FG_FACTSET_IND` are the **verified-working** classification fields for this user's entitlement. `FG_GICS_INDUSTRY` is from the reference library (GICS variants returned no data in this entitlement) and is kept for completeness.

## Formula index — Corporate actions / events

| Key | Label | Family | FQL template |
|-----|-------|--------|--------------|
| `earnings_date_next` | Next earnings-release date (**optional**, event field) — **=FDSLIVE** | corporate_actions | `RTP_EARNINGS_RELEASE_DATE` |
| `earnings_release_status` | Earnings-release status (**optional**, event field) — **=FDSLIVE** | corporate_actions | `RTP_EARNINGS_RELEASE_STATUS` |
| `ex_dividend_date` | Ex-dividend date (**optional**, event field) — `=FDS` | corporate_actions | `FCA_EVENT_DATE(0,"CASH_DIST","EXDATE","YYYYMMDD")` |

> **Event fields (user-tested).** `earnings_date_next` (`RTP_EARNINGS_RELEASE_DATE`, returns `YYYYMMDD` int e.g. `20260831`) and `earnings_release_status` (`RTP_EARNINGS_RELEASE_STATUS`, returns text e.g. `"Projected"`/`"Confirmed"`) are LIVE real-time RTP_ fields that MUST be pulled with **`=FDSLIVE`** (NOT `=FDS`), e.g. `=FDSLIVE(A2,"RTP_EARNINGS_RELEASE_DATE")` / `=FDSLIVE(A2,"RTP_EARNINGS_RELEASE_STATUS")`; no date args, no nested quotes. `ex_dividend_date` returns `YYYYMMDD` (e.g. `20260526`) via a standard `=FDS` `FCA_EVENT_DATE` pull. They are OPTIONAL per-ticker pulls used for deterministic MECHANICAL_DISLOCATION tagging in the research note.
>
> **`FCA_EVENT_DATE` quoting.** Inside `=FDS(...)` the nested string args need **doubled** double-quotes (same escaping `=FDS` uses for any embedded string). The emitted cell must be:
> ```
> =FDS("9988-HK","FCA_EVENT_DATE(0,""CASH_DIST"",""EXDATE"",""YYYYMMDD"")")
> ```

## Estimates functions

### FE_ESTIMATE

```
FE_ESTIMATE(item, statistic, report_basis, estimate_period, sdate, edate, frq, 'CONTEXT')
```

Example: `=FDS(A1,"FE_ESTIMATE(EPS,MEAN,ANNUAL,+1,sdate,edate,frq)")`

**Statistics:**

| Statistic | | Statistic | |
|---|---|---|---|
| `MEAN` | | `MED` | |
| `NEST` | | `STDDEV` | |
| `HIGH` | | `LOW` | |
| `LAST` | | `OLDEST` | |
| `UP` | | `DOWN` | |
| `MARK` | | `TOTAL` | |
| `UNCHGED` | | `COEFFVAR` | |

**Report basis:**

| Code | Meaning |
|------|---------|
| `ANNUAL` | annual (alias ANN) |
| `QUARTERLY` | quarterly (alias QTR) |
| `SEMI` | semiannual |
| `CALA` | calendarized time-weighted annual |
| `CALQ` | calendarized time-weighted quarterly |
| `CAL4` | calendarized 4-quarter sum |
| `LTMA` | last twelve months time-weighted annual |
| `LTM4_ROLL` | last twelve months 4-quarter sum |
| `NTMA` | next twelve months time-weighted annual |
| `NTM4_ROLL` | next twelve months 4-quarter sum |
| `STMA` | second twelve months time-weighted annual |
| `STM4_ROLL` | second twelve months 4-quarter sum |
| `SLTMA` | second last twelve months time-weighted annual |

_Append _ROLL for rolling vs non-rolling on ANNUAL/QUARTERLY/CALA/CALQ._

**Estimate period options:**

| Frequency | Period syntax |
|-----------|---------------|
| Annual | FY1-FY4, forward +n, or absolute YYYY |
| Quarterly | FQ1-FQ5, forward +n, fiscal qtr YYYY/nF |
| Semiannual | FH1-FH4, forward +n, YYYY/nF |
| CalendarizedAnnual | CY1-CY4, +n, absolute YYYY |
| CalendarizedQuarterly | absolute YYYY/nC |
| LTM_NTM_STM | no period needed |

_NTM sums the next four unreported quarter estimates as of calc date (a.k.a. Twelve Month Forward)._

**Date function:** `FE_ESTIMATE_DATE(date_type, , report_basis, estimate_period, 'MM/DD/YYYY', 0, , '')` — date types: `FISCALPERIODEND` (fiscal period the estimate forecasts), `DATE` (date the consensus is calculated for).

### FE_ACTUAL

```
FE_ACTUAL(ACTUAL, item, report_basis, period, , , , '')
```
Example: `FE_ACTUAL(ACTUAL,EPS,ANNUAL,0,,,,'')` — date function `FE_ACTUAL_DATE(FISCALPERIODEND,,ANNUAL,0,'MM/DD/YYYY')`.

### FE_VALUATION

```
FE_VALUATION(item, statistic, report_basis, period, ...)
```

- NTM P/E (native): `FE_VALUATION(PE,MEAN,NTMA,,0,,,'')`
- FY1 P/E (native): `FE_VALUATION(PE,MEAN,ANNUAL,+1,0,,,'')`

**Prebuilt estimate templates:**

| Label | Code |
|-------|------|
| FY1 Mean EPS | `FE_ESTIMATE(EPS,MEAN,ANNUAL,+1,0,,,'')` |
| FY1 Mean EPS - Rolling | `FE_ESTIMATE(EPS,MEAN,ANNUAL_ROLL,+1,0,,,'')` |
| FY2 Mean EPS - Rolling | `FE_ESTIMATE(EPS,MEAN,ANNUAL_ROLL,+2,0,,,'')` |
| FQ1 Mean EPS - Rolling | `FE_ESTIMATE(EPS,MEAN,QUARTERLY_ROLL,+1,0,,,'')` |
| FY1 Mean Sales - Rolling | `FE_ESTIMATE(SALES,MEAN,ANNUAL_ROLL,+1,0,,,'')` |
| NTM EPS - Rolling | `FE_ESTIMATE(EPS,MEAN,NTMA,,0,,,'')` |
| Long-Term Growth Mean | `FE_ESTIMATE(EPS_LTG,MEAN,,,0,,,'')` |
| Calendarized EPS | `FE_ESTIMATE(EPS,MEAN,CALA,1CY,0,,,'')` |

## Report layout codes

> Directional codes appear only in the template, never in the output data file.

| Code | Behavior |
|------|----------|
| `default` | Symbols down a column, request codes on same row as first symbol. No code needed. |
| `^COL` | Place before request codes. Symbols across a row; data codes in columns below. Scans down columns. |
| `^ROW` | Switches back to symbols-down-a-column after a ^COL section. May alternate any number of times. |
| `^SHEET` | Place before requests. Spreads symbols across worksheets; template is sheet 1; symbols occupy same cell on each subsequent sheet. |
| `blank_rows_cols` | Allowed in any layout; useful for time-series (e.g. 4 quarters down a column needs 4 blank rows between symbols). |

## Estimate item keywords

_Use 'keyword' as the item arg in FE_ESTIMATE/FE_ACTUAL/FE_VALUATION. 'norm' is the uppercase normalized form for lookup._

**Total keyword entries: 599** across standard + sector groups. Use `keyword` as the item arg in `FE_ESTIMATE` / `FE_ACTUAL` / `FE_VALUATION`; `norm` is the uppercase lookup form.

### Standard (cross-sector)

| Label | Keyword | Norm |
|-------|---------|------|
| Accounts Payable | `PAY_ACCT` | `PAY_ACCT` |
| Accounts Receivable | `RECEIV_NET` | `RECEIV_NET` |
| Annual Recurring Revenue | `ARR` | `ARR` |
| Applied Cap Rate (%) | `APP_CAP_RATE` | `APP_CAP_RATE` |
| Average Selling Price | `ASP` | `ASP` |
| Book Return on Equity | `BOOK_ROE` | `BOOK_ROE` |
| Book Value per Share | `BPS` | `BPS` |
| Book Value per Share - Tangible | `BPS_TANG` | `BPS_TANG` |
| Capital Expenditures | `CAPEX` | `CAPEX` |
| Capitalized Research & Development | `CAP_RD` | `CAP_RD` |
| Cash and Cash Equivalents | `CASH_ST` | `CASH_ST` |
| Cash Flow from Financing | `CF_FIN` | `CF_FIN` |
| Cash Flow from Investing | `CF_INV` | `CF_INV` |
| Cash Flow from Operations | `CF_OP` | `CF_OP` |
| Cash Flow from Operations - GAAP | `CFO_GAAP` | `CFO_GAAP` |
| Cash Flow per Share | `CFPS` | `CFPS` |
| Cash Net Income | `CASH_NP` | `CASH_NP` |
| Cash Net Income from Continuing Operations | `CASH_NP_CONT` | `CASH_NP_CONT` |
| Change in Working Capital | `WKCAP_CHG` | `WKCAP_CHG` |
| Compensation Ratio (%) | `COMP_RATIO` | `COMP_RATIO` |
| Constant Currency Revenue Growth (%) | `CCUR_GRTH` | `CCUR_GRTH` |
| Cost of Debt (%) | `COS_DEBT` | `COS_DEBT` |
| Cost of Sales | `COS` | `COS` |
| Current Assets | `ASSETS_CURR` | `ASSETS_CURR` |
| Current Liabilities | `LIABS_CURR` | `LIABS_CURR` |
| Depr. & Amort. | `DEP_AMORT_EXP` | `DEP_AMORT_EXP` |
| Total Deferred Revenues | `DEFREVENUE` | `DEFREVENUE` |
| Deferred Revenues - ST | `DEFREVENUE_ST` | `DEFREVENUE_ST` |
| Deferred Revenues - LT | `DEFREVENUE_LT` | `DEFREVENUE_LT` |
| Discretionary Cash Flow | `DISCR_CF` | `DISCR_CF` |
| Dividends per Share | `DPS` | `DPS` |
| EPS | `EPS` | `EPS` |
| EPS - Non GAAP ex. SOE | `EPS_EX_XORD` | `EPS_EX_XORD` |
| EPS - ex. Extraordinary Items - Diluted | `EPSAD` | `EPSAD` |
| EPS - GAAP | `EPS_GAAP` | `EPS_GAAP` |
| EPS - Reported Diluted | `EPSRD` | `EPSRD` |
| EPS - Consolidated | `EPS_C` | `EPS_C` |
| EPS - Non Consolidated | `EPS_P` | `EPS_P` |
| EPS - Non GAAP | `EPS_NONGAAP` | `EPS_NONGAAP` |
| EPS - Headline Basic | `HEPSB` | `HEPSB` |
| EPS - Headline Diluted | `HEPSD` | `HEPSD` |
| Operating Income | `EBIT` | `EBIT` |
| Operating Income - Non GAAP | `EBIT_ADJ` | `EBIT_ADJ` |
| EBIT - Consolidated | `EBIT_C` | `EBIT_C` |
| EBIT - Non Consolidated | `EBIT_P` | `EBIT_P` |
| Operating Income - GAAP | `EBIT_REP` | `EBIT_REP` |
| EBITDA | `EBITDA` | `EBITDA` |
| EBITDA Non-GAAP | `EBITDA_ADJ` | `EBITDA_ADJ` |
| EBITDA - Consolidated | `EBITDA_C` | `EBITDA_C` |
| EBITDA - Non Consolidated | `EBITDA_P` | `EBITDA_P` |
| EBITDA GAAP | `EBITDA_REP` | `EBITDA_REP` |
| EBITDA after Lease | `EBITDAAL` | `EBITDAAL` |
| EBITDA after Lease - Adjusted | `EBITDAAL_ADJ` | `EBITDAAL_ADJ` |
| EBITDA after Lease - Reported | `EBITDAAL_REP` | `EBITDAAL_REP` |
| EBITDAX | `EBITDAX` | `EBITDAX` |
| Equipment Expense | `PPE_EXP` | `PPE_EXP` |
| Equity Ratio (%) | `EQ_RATIO` | `EQ_RATIO` |
| FFO/Debt (%) | `FFO_DEBT` | `FFO_DEBT` |
| Free Cash Flow | `FCF` | `FCF` |
| Free Cash Flow per Share | `FCFPS` | `FCFPS` |
| Unlevered Free Cash Flow | `UFCF` | `UFCF` |
| General & Admin Expense | `G_A_EXP` | `G_A_EXP` |
| Gross Income | `GROSS_INC` | `GROSS_INC` |
| Gross Merchandise Volume | `GMV` | `GMV` |
| Intangible Assets | `INTANG` | `INTANG` |
| Interest Coverage Ratio (X) | `INT_COVER_RATIO` | `INT_COVER_RATIO` |
| Interest Expense | `INT_EXP` | `INT_EXP` |
| Interest Income | `INT_INCOME` | `INT_INCOME` |
| Inventories | `INVEN` | `INVEN` |
| Local Currency Revenue Growth (%) | `LCUR_GRTH` | `LCUR_GRTH` |
| Long-Term Debt | `DEBT_LT` | `DEBT_LT` |
| Long Term Growth (%) | `EPS_LTG` | `EPS_LTG` |
| Long-Term Investments | `INVEST_LT` | `INVEST_LT` |
| Maintenance CAPEX | `MAINT_CAPEX` | `MAINT_CAPEX` |
| Minority Interest | `MINTEREST` | `MINTEREST` |
| NAVPS | `NAVPS` | `NAVPS` |
| NAV - NTM | `RNAVPS` | `RNAVPS` |
| Net Debt | `NET_DEBT` | `NET_DEBT` |
| Net Income | `NET_INC` | `NET_INC` |
| Net Income - Non GAAP | `NET_INC_ADJ` | `NET_INC_ADJ` |
| Net Income - Consolidated | `NET_INC_C` | `NET_INC_C` |
| Net Income - Non Consolidated | `NET_P` | `NET_P` |
| Net Income - GAAP | `NET_INC_REP` | `NET_INC_REP` |
| Net Sales | `NET_SALES` | `NET_SALES` |
| Operating Expense | `OPER_EXP` | `OPER_EXP` |
| Operating Lease Expenses | `OP_LEASE_EXP` | `OP_LEASE_EXP` |
| Operating Ratio (%) | `OP_RATIO` | `OP_RATIO` |
| Organic Growth (%) | `ORGANICGROWTH` | `ORGANICGROWTH` |
| Pension & Benefits | `PENS_BENF` | `PENS_BENF` |
| Pretax Income | `PTX_INC` | `PTX_INC` |
| Pretax Income - Non GAAP | `PTX_INC_ADJ` | `PTX_INC_ADJ` |
| PTP - Consolidated | `PTX_INC_C` | `PTX_INC_C` |
| PTP - Non Consolidated | `PTX_INC_P` | `PTX_INC_P` |
| Pretax Income - GAAP | `PTX_INC_REP` | `PTX_INC_REP` |
| Research & Development | `RD_EXP` | `RD_EXP` |
| Compensation and Benefits | `SAL_BENEFITS` | `SAL_BENEFITS` |
| Sales | `Sales` | `SALES` |
| Sales - Consolidated | `SALES_C` | `SALES_C` |
| Sales - Non Consolidated | `SALES_P` | `SALES_P` |
| Same Store NOI (%) | `SS_NOI` | `SS_NOI` |
| Selling & Marketing Expense | `S_M_EXP` | `S_M_EXP` |
| SG&A Expense | `SGA` | `SGA` |
| Shareholder Equity | `SHLDRS_EQ` | `SHLDRS_EQ` |
| Share Repurchase | `SHS_REPURCH` | `SHS_REPURCH` |
| Short-Term Debt | `DEBT_ST` | `DEBT_ST` |
| Stock Option Expense - Per Share | `SOE` | `SOE` |
| Target Price | `PRICE_TGT` | `PRICE_TGT` |
| Tax Expense | `INC_TAX` | `INC_TAX` |
| Total Assets | `ASSETS` | `ASSETS` |
| Total Capital | `TOTAL_CAPITAL` | `TOTAL_CAPITAL` |
| Total Debt | `DEBT` | `DEBT` |
| Total Goodwill | `GW_TOT` | `GW_TOT` |
| Total Payment Volume | `TPV` | `TPV` |
| Total Revenues | `REV_TOT` | `REV_TOT` |
| Weighted Average Cost of Capital (%) | `WACC` | `WACC` |
| Working Capital | `WKCAP` | `WKCAP` |

### Airlines

| Label | Keyword | Norm |
|-------|---------|------|
| Available Seat Km (millions) | `AVAILABLESEATKM` | `AVAILABLESEATKM` |
| Load Factor (%) | `LOADFACTOR` | `LOADFACTOR` |
| OPEX / ASK | `OPEX_ASK` | `OPEX_ASK` |
| OPEX / ASK excl. Fuel | `OPEX_ASK_XFUEL` | `OPEX_ASK_XFUEL` |
| Revenue Passenger (thousands) | `REV_PASSENGER` | `REV_PASSENGER` |
| Passenger Revenue per ASK | `PASS_REV_ASK` | `PASS_REV_ASK` |
| Revenue Passenger Km | `REVPASSENGERKM` | `REVPASSENGERKM` |
| Passenger Revenue per RPK | `PASS_REV_RPK` | `PASS_REV_RPK` |
| Total Revenue per ASK | `TOT_REV_ASK` | `TOT_REV_ASK` |

### Banks

| Label | Keyword | Norm |
|-------|---------|------|
| Amortization of Intangibles | `AMORT_INTANG` | `AMORT_INTANG` |
| Bank owned life insurance | `BOLI` | `BOLI` |
| Card Income | `CARD_INCOME` | `CARD_INCOME` |
| Common Equity Tier 1 (CET1) | `COM_EQUITY_TIER1` | `COM_EQUITY_TIER1` |
| Efficiency Ratio | `COST_INCOME` | `COST_INCOME` |
| Deposits - EOP | `DEPS` | `DEPS` |
| Deposits - Average | `DEPS_AVG` | `DEPS_AVG` |
| Average Earning Assets | `AVG_EARN_ASSETS` | `AVG_EARN_ASSETS` |
| FDIC Insurance expense | `FDIC` | `FDIC` |
| Foreign Exchange and Other Trading Revenue | `FOREX_OTHERTRAD` | `FOREX_OTHERTRAD` |
| Income from Fees & Commissions | `INC_FEES` | `INC_FEES` |
| Insurance Commissions | `INS_INC` | `INS_INC` |
| Investment Banking & Trust | `INV_BANK_TRUST` | `INV_BANK_TRUST` |
| Investment Management Fees | `INV_MNGT_FEES` | `INV_MNGT_FEES` |
| Investment Services Fees | `INV_SERV_FEES` | `INV_SERV_FEES` |
| Lending & Deposit Related Fees | `LEND_DEPS_FEE` | `LEND_DEPS_FEE` |
| Leverage Ratio (%) | `LEV_RATIO` | `LEV_RATIO` |
| Leverage Exposure | `LEV_EXP` | `LEV_EXP` |
| Loan Loss Provision/Loans (%) | `LOANLOSSPROV_PCT` | `LOANLOSSPROV_PCT` |
| Loan Loss Reserve | `LOAN_LOSS_RSRV` | `LOAN_LOSS_RSRV` |
| Loan Loss Reserve Ratio (%) | `LOANLOSSRSV_PCT` | `LOANLOSSRSV_PCT` |
| Mortgage Banking | `MORTGAGE_BANKING` | `MORTGAGE_BANKING` |
| Net Charge-Offs | `NET_CHARGE_OFFS` | `NET_CHARGE_OFFS` |
| Non-Compensation Expense | `NON_COMP_EXP` | `NON_COMP_EXP` |
| Non-Interest Income | `NON_INT_INC` | `NON_INT_INC` |
| Loans - EOP | `LOAN_NET` | `LOAN_NET` |
| AT1 Distributions | `AT1_DISTR` | `AT1_DISTR` |
| Average Interest Bearing Deposits | `AVG_INTB_DEPS` | `AVG_INTB_DEPS` |
| Average Interest Bearing Deposits Cost (%) | `AVG_INTB_DEPS_COS` | `AVG_INTB_DEPS_COS` |
| Average Interest Bearing Liabilities | `AVG_INTB_LIABS` | `AVG_INTB_LIABS` |
| Average Interest Bearing Liabilities Cost (%) | `AVG_INTB_LIABS_COS` | `AVG_INTB_LIABS_COS` |
| Loans - Average | `LOAN_NET_AVG` | `LOAN_NET_AVG` |
| Average Non-Interest Bearing Deposits | `AVG_NINTB_DEPS` | `AVG_NINTB_DEPS` |
| Net Interest Income | `INT_INC_NET` | `INT_INC_NET` |
| Net Interest Margin (%) | `INT_INC_MARGIN` | `INT_INC_MARGIN` |
| Non-Performing Assets | `ASSETS_NONPERF` | `ASSETS_NONPERF` |
| Non-Performing Loans | `LOAN_NONPERF` | `LOAN_NONPERF` |
| NPAs/Loan+OREO (%) | `LOANOREO_NONPERF` | `LOANOREO_NONPERF` |
| NPL Coverage Ratio (%) | `NPL_COV_RTO` | `NPL_COV_RTO` |
| Occupancy Expense | `OCCUPY_EXP` | `OCCUPY_EXP` |
| Occupancy & Equipment Expense | `EQUIP_EXP` | `EQUIP_EXP` |
| OREO Expense | `OREO_EXP` | `OREO_EXP` |
| Origination Volume | `ORIGIN_VOL` | `ORIGIN_VOL` |
| Professional Fees | `PROF_FEES_EXP` | `PROF_FEES_EXP` |
| Provision for Credit Losses | `LOAN_PROV` | `LOAN_PROV` |
| Reserve Build | `RSRV_BUILD` | `RSRV_BUILD` |
| Return on Tangible Equity (RoTE) (%) | `ROTE` | `ROTE` |
| Risk Weighted Assets | `ASSETS_RISK_WGHT` | `ASSETS_RISK_WGHT` |
| Service Charges on Deposits | `SERVICE_CHRG` | `SERVICE_CHRG` |
| Software and Processing Fees | `SOFT_PROC_FEES` | `SOFT_PROC_FEES` |
| Software / IT Systems | `SOFT_IT_SYS` | `SOFT_IT_SYS` |
| Tangible Common Equity/Tangible Assets (%) | `TCE_TA` | `TCE_TA` |
| Texas Ratio (%) | `TEXAS_RATIO` | `TEXAS_RATIO` |
| Tier 1 Capital | `TIER1_CAP` | `TIER1_CAP` |
| Tier 1 Capital Ratio (%) | `CAP_RATIO_TIER1` | `CAP_RATIO_TIER1` |
| Tier 1 Common Capital Ratio (%) | `COMCAP_RATIO_TIER1` | `COMCAP_RATIO_TIER1` |
| Tier 1 Common Fully Loaded Ratio (%) | `COMLOAD_RATIO_T1` | `COMLOAD_RATIO_T1` |
| Tier 1 Leverage Ratio (%) | `LEV_RATIO_TIER1` | `LEV_RATIO_TIER1` |
| Tier 2 Capital Ratio (%) | `CAP_RATIO_TIER2` | `CAP_RATIO_TIER2` |
| Total Capital Ratio (%) | `CAP_RATIO_TOT` | `CAP_RATIO_TOT` |
| Total OREO | `TOT_OREO` | `TOT_OREO` |
| Total Risk-based Capital | `RISK_BASED_CAP` | `RISK_BASED_CAP` |
| Trading Income | `INC_TRADING` | `INC_TRADING` |
| Transaction Processing Services | `TRANS_PROC_SERV` | `TRANS_PROC_SERV` |
| Trust and Asset Management | `TRUST_INC` | `TRUST_INC` |

### Misc sectors

| Label | Keyword | Norm |
|-------|---------|------|
| Total Addressable Market _(sector: Computer Hardware)_ | `TAM` | `TAM` |
| Total Student Enrollment _(sector: Education)_ | `STUDENTENROLL_TOT` | `STUDENTENROLL_TOT` |
| New Student Enrollment _(sector: Education)_ | `STUDENTENROLL_NEW` | `STUDENTENROLL_NEW` |
| Annual Subscription Value _(sector: Financial Data Provider)_ | `ASV` | `ASV` |
| EUR/JPY _(sector: Forex)_ | `EUR_JPY` | `EUR_JPY` |
| USD/JPY _(sector: Forex)_ | `USD_JPY` | `USD_JPY` |
| Restaurant Margin (%) _(sector: Restaurant)_ | `REST_MARG` | `REST_MARG` |
| Daily Active Users (millions) _(sector: Social Media/Games)_ | `DAU` | `DAU` |
| Monthly Active Users (millions) _(sector: Social Media/Games)_ | `MAU` | `MAU` |
| Monthly Unique Users (millions) _(sector: Social Media/Games)_ | `MUU` | `MUU` |
| Revenue Per Unit (%) _(sector: Transportation)_ | `REV_UNIT` | `REV_UNIT` |
| Volume Growth (%) _(sector: Transportation)_ | `VOL_GRTH` | `VOL_GRTH` |

### Home Builders

| Label | Keyword | Norm |
|-------|---------|------|
| New Orders Units | `NEW_ORDERS_UNITS` | `NEW_ORDERS_UNITS` |
| New Orders Avg Price (000's) | `NEW_ORD_PRICE` | `NEW_ORD_PRICE` |
| New Orders Value (M) | `NEW_ORDERS_VALUE` | `NEW_ORDERS_VALUE` |
| Backlog Units | `BACKLOG_UNITS` | `BACKLOG_UNITS` |
| Backlog Avg Price (000's) | `BACKLOG_AVG_PRICE` | `BACKLOG_AVG_PRICE` |
| Backlog Value (M) | `BACKLOG_VALUE` | `BACKLOG_VALUE` |
| Cancellation Rate (%) | `CANCELRATE` | `CANCELRATE` |
| Deliveries Units | `DELIVERIES_UNITS` | `DELIVERIES_UNITS` |
| Deliveries Avg Price (000's) | `DELIV_PRICE` | `DELIV_PRICE` |
| Home Sales | `HOME_SALES` | `HOME_SALES` |
| Land Sales | `LAND_SALES` | `LAND_SALES` |
| Financial Services | `FIN_SERVICES` | `FIN_SERVICES` |

### Hospitals

| Label | Keyword | Norm |
|-------|---------|------|
| Bad Debt Provisions | `BAD_DEBT_PROV` | `BAD_DEBT_PROV` |
| Medical Cost Ratio (%) | `MCR` | `MCR` |
| Supplies | `SUPPLIES` | `SUPPLIES` |
| Other Operating Expense | `OTHER_OPEX` | `OTHER_OPEX` |
| SS Admissions (%) | `SS_ADM` | `SS_ADM` |
| SS Adjusted Admissions (%) | `SS_ADJ_ADM` | `SS_ADJ_ADM` |
| SS Revenue Per Adjusted Admissions (%) | `SS_REV_PER_ADJ_ADM` | `SS_REV_PER_ADJ_ADM` |

### Hotels

| Label | Keyword | Norm |
|-------|---------|------|
| Average Daily Rate (ADR) | `ROOM_RATE_DAILY_TOT` | `ROOM_RATE_DAILY_TOT` |
| ADR - Dom. | `ROOM_RATE_DAILY_DOM` | `ROOM_RATE_DAILY_DOM` |
| ADR - Intl. | `ROOM_RATE_DAILY_INTL` | `ROOM_RATE_DAILY_INTL` |
| Occupancy (%) | `OCCUPY_RATE_TOT` | `OCCUPY_RATE_TOT` |
| Occupancy, Dom (%) | `OCCUPY_RATE_DOM` | `OCCUPY_RATE_DOM` |
| Occupancy, Intl (%) | `OCCUPY_RATE_INTL` | `OCCUPY_RATE_INTL` |
| RevPAR | `REV_PER_ROOM_TOT` | `REV_PER_ROOM_TOT` |
| RevPAR - Dom. | `REV_PER_ROOM_DOM` | `REV_PER_ROOM_DOM` |
| RevPAR - Intl. | `REV_PER_ROOM_INTL` | `REV_PER_ROOM_INTL` |

### Insurance

| Label | Keyword | Norm |
|-------|---------|------|
| Adjusted Net Worth | `ADJ_NETWORTH` | `ADJ_NETWORTH` |
| Annualized Premium Equivalent | `ANN_PREM_EQ` | `ANN_PREM_EQ` |
| Benefit Ratio (%) | `BENEFIT_RATIO` | `BENEFIT_RATIO` |
| Book Value Per Share - Excl AOCI | `BVPS_EXCL_AOCI` | `BVPS_EXCL_AOCI` |
| Book Value Per Share - Incl AOCI | `BVPS_INCL_AOCI` | `BVPS_INCL_AOCI` |
| Cat Losses | `CAT_LOSSES` | `CAT_LOSSES` |
| Cat Losses (%) | `CAT_LOSSES_RATIO` | `CAT_LOSSES_RATIO` |
| Claims Expense | `CLAIMS_EXP` | `CLAIMS_EXP` |
| Combined Ratio (%) | `COMBINED_RATIO` | `COMBINED_RATIO` |
| Deferred Acquisition Costs | `DEFACQUI_COST` | `DEFACQUI_COST` |
| Eligible Own Funds | `ELIG_OWN_FUND` | `ELIG_OWN_FUND` |
| Eligible Restricted Tier 1 Capital | `ELIG_RES_TIER1_CAP` | `ELIG_RES_TIER1_CAP` |
| Eligible Tier 2 Capital | `ELIG_TIER2_CAP` | `ELIG_TIER2_CAP` |
| Eligible Tier 3 Capital | `ELIG_TIER3_CAP` | `ELIG_TIER3_CAP` |
| Eligible Unrestricted Tier 1 Capital | `ELIG_UNRES_TIER1_CAP` | `ELIG_UNRES_TIER1_CAP` |
| Embedded Value | `EMBEDDED_GROSS` | `EMBEDDED_GROSS` |
| Embedded Value Operating Profit (EVOP) | `EV_OP` | `EV_OP` |
| Embedded Value Profit | `EV_PROF` | `EV_PROF` |
| Embedded Value Per Share | `EMBEDDED_VALUE` | `EMBEDDED_VALUE` |
| Expense Ratio (%) | `EXPENSE_RATIO` | `EXPENSE_RATIO` |
| Fees | `FEES` | `FEES` |
| Gross Premiums Written | `GROSS_PREM_WRITTEN` | `GROSS_PREM_WRITTEN` |
| Gross Premiums Written - Life | `GPW_LIFE` | `GPW_LIFE` |
| Gross Premiums Written - P&C | `GPW_PC` | `GPW_PC` |
| Insurance Profit | `INS_PROFIT` | `INS_PROFIT` |
| Insurance Reserves | `INS_RSRV` | `INS_RSRV` |
| Insurance Service Result | `INS_SERV_RESULT` | `INS_SERV_RESULT` |
| Invested Assets | `INVEST_ASSETS` | `INVEST_ASSETS` |
| Life Insurance Claims | `LIFE_INS_CLAIMS` | `LIFE_INS_CLAIMS` |
| Loss Ratio (%) | `LOSS_RATIO` | `LOSS_RATIO` |
| Net Financial Result | `NET_FIN_RESULT` | `NET_FIN_RESULT` |
| Net Investment Income | `INVEST_INC` | `INVEST_INC` |
| Net Investment Income - Life | `INVEST_INC_LIFE` | `INVEST_INC_LIFE` |
| Net Investment Income - P&C | `INVEST_INC_PC` | `INVEST_INC_PC` |
| Net Investment Yield (%) | `NET_INVEST_YIELD` | `NET_INVEST_YIELD` |
| Net Premiums Earned | `PREM_EARN` | `PREM_EARN` |
| Net Premiums Earned - Life | `NPE_LIFE` | `NPE_LIFE` |
| Net Premiums Earned - P&C | `NPE_PC` | `NPE_PC` |
| Net Premiums Written | `PREM_WRITTEN` | `PREM_WRITTEN` |
| Net Premiums Written - Life | `NPW_LIFE` | `NPW_LIFE` |
| Net Premiums Written - P&C | `NPW_PC` | `NPW_PC` |
| New Business Premium | `NEW_BUSI_PREM` | `NEW_BUSI_PREM` |
| New Business Multiple | `NEW_BUSI_MULT` | `NEW_BUSI_MULT` |
| Number of Policies in Force | `PIF_NB` | `PIF_NB` |
| Operating Capital Generation | `OPER_CAP_GEN` | `OPER_CAP_GEN` |
| Present Value of New Business Premium (PVNBP) | `PV_NBP` | `PV_NBP` |
| Prior Year Development | `PRIOR_YR_DEV` | `PRIOR_YR_DEV` |
| Return on Embedded Value (%) | `RETURN_EV` | `RETURN_EV` |
| Solvency Ratio (%) | `SOL_RATIO` | `SOL_RATIO` |
| Solvency II Ratio (%) | `SOL_2_RATIO` | `SOL_2_RATIO` |
| Surrenders | `INS_EQ_POL` | `INS_EQ_POL` |
| Total Equity Securities Investment | `EQUITY_INV` | `EQUITY_INV` |
| Total Fixed Income Securities Investment | `FIXED_INCOME_INV` | `FIXED_INCOME_INV` |
| Underlying Combined Ratio (%) | `COMB_RATIO_UND` | `COMB_RATIO_UND` |
| Underlying Loss Ratio (%) | `LOSS_RATIO_UND` | `LOSS_RATIO_UND` |
| Underwriting Expense (millions) | `UW_EXP` | `UW_EXP` |
| Underwriting Income | `UW_INCOME` | `UW_INCOME` |
| Underwriting Income - Life | `UW_INCOME_LIFE` | `UW_INCOME_LIFE` |
| Underwriting Income - P&C | `UW_INCOME_PC` | `UW_INCOME_PC` |
| Value of In-Force | `VALUE_IN_FORCE` | `VALUE_IN_FORCE` |
| Value of New Business | `VALUE_NEW_BUSI` | `VALUE_NEW_BUSI` |
| VNB Margin (%) | `VNB_MARGIN` | `VNB_MARGIN` |

### Marijuana

| Label | Keyword | Norm |
|-------|---------|------|
| Marijuana - Cost per Gram | `COST_PER_GRAM` | `COST_PER_GRAM` |
| Marijuana - Kg of Cannabis Sold | `KG_CANNABIS_SOLD` | `KG_CANNABIS_SOLD` |
| Production Costs | `PROD_COSTS` | `PROD_COSTS` |

### Mining

#### Mining — Metal Prices

| Label | Keyword | Norm |
|-------|---------|------|
| Alumina Metal Price | `PRICE_ALUMIN_TON` | `PRICE_ALUMIN_TON` |
| Aluminum Metal Price | `PRICE_ALUM_TON` | `PRICE_ALUM_TON` |
| Bauxite Metal Price | `PRICE_BAUX_TON` | `PRICE_BAUX_TON` |
| Cobalt Metal Price | `PRICE_COBALT_LBS` | `PRICE_COBALT_LBS` |
| Copper Metal Price | `PRICE_COPPER_TON` | `PRICE_COPPER_TON` |
| Diamond Metal Price | `PRICE_DIAM_CT` | `PRICE_DIAM_CT` |
| Gold Metal Price | `PRICE_GOLD_OZ` | `PRICE_GOLD_OZ` |
| Iron Ore Fines (CFR) Metal Price | `PRICE_IRONFINCFR` | `PRICE_IRONFINCFR` |
| Iron Ore Fines (FOB) Metal Price | `PRICE_IRONFINFOB` | `PRICE_IRONFINFOB` |
| Iron Ore Lump (CFR) Metal Price | `PRICE_IRONLUMCFR` | `PRICE_IRONLUMCFR` |
| Iron Ore Lump (FOB) Metal Price | `PRICE_IRONLUMFOB` | `PRICE_IRONLUMFOB` |
| Lead Metal Price | `PRICE_LEAD_TON` | `PRICE_LEAD_TON` |
| Lithium Metal Price | `PRICE_LITH_TON` | `PRICE_LITH_TON` |
| Metallurgical Coal Metal Price | `PRICE_M_COAL_TON` | `PRICE_M_COAL_TON` |
| Molybdenum Metal Price | `PRICE_MOLY_LBS` | `PRICE_MOLY_LBS` |
| Nickel Metal Price | `PRICE_NICKEL_TON` | `PRICE_NICKEL_TON` |
| Palladium Metal Price | `PRICE_PALLAD_OZ` | `PRICE_PALLAD_OZ` |
| Phosphate Metal Price | `PRICE_PHOSPH_TON` | `PRICE_PHOSPH_TON` |
| Platinum Metal Price | `PRICE_PLAT_OZ` | `PRICE_PLAT_OZ` |
| Potash Metal Price | `PRICE_POTASH_TON` | `PRICE_POTASH_TON` |
| Rhodium Metal Price | `PRICE_RHOD_OZ` | `PRICE_RHOD_OZ` |
| Silver Metal Price | `PRICE_SILVER_OZ` | `PRICE_SILVER_OZ` |
| Thermal Coal Metal Price | `PRICE_T_COAL_TON` | `PRICE_T_COAL_TON` |
| Tin Metal Price | `PRICE_TIN_TON` | `PRICE_TIN_TON` |
| Uranium Metal Price | `PRICE_URAN_LBS` | `PRICE_URAN_LBS` |
| Vanadium Metal Price | `PRICE_VANA_LBS` | `PRICE_VANA_LBS` |
| Zinc Metal Price | `PRICE_ZINC_TON` | `PRICE_ZINC_TON` |

#### Mining — Cost Curve Pattern

```
{
  "template": "{METAL}_{COST_TYPE}_{PRODUCT_BASIS}",
  "metals": [
    "COPPER",
    "COAL",
    "GOLD",
    "FE",
    "NICKEL",
    "SILVER",
    "U",
    "ZINC"
  ],
  "cost_types": {
    "AIC": "All-In Cost",
    "AISC": "All-In Sustaining Cost",
    "CASHCOST": "Cash Cost"
  },
  "product_basis": {
    "BP": "By Product",
    "CP": "Co Product",
    "EQ": "Equivalent"
  },
  "example": "GOLD_AISC_EQ, COPPER_CASHCOST_BP",
  "note": "FE prefix = Iron; U prefix = Uranium"
}
```

#### Mining — Production Volumes

| Label | Keyword | Norm |
|-------|---------|------|
| Total Production | `TOTAL_PROD` | `TOTAL_PROD` |
| Total Production Alumina (t) | `PROD_ALUN` | `PROD_ALUN` |
| Total Production Aluminium (t) | `PROD_ALUM` | `PROD_ALUM` |
| Total Production Bauxite (t) | `PROD_BAUX` | `PROD_BAUX` |
| Total Production Borates (t) | `PROD_BORATES` | `PROD_BORATES` |
| Total Production Chrome Ore (t) | `PROD_CHROMEORE` | `PROD_CHROMEORE` |
| Total Production Coal (t) | `PROD_COAL` | `PROD_COAL` |
| Total Production Cobalt (t) | `PROD_COBALT` | `PROD_COBALT` |
| Total Production Cobalt Concentrate (t) | `PROD_COBCON` | `PROD_COBCON` |
| Total Production Coke (t) | `PROD_COKE` | `PROD_COKE` |
| Total Production Copper (t) | `PROD_COPP` | `PROD_COPP` |
| Total Production Copper Cathode (t) | `PROD_CATH` | `PROD_CATH` |
| Total Production Copper Concentrate (t) | `PROD_COPPCON` | `PROD_COPPCON` |
| Total Production Copper Smelting (t) | `PROD_COPPSMELT` | `PROD_COPPSMELT` |
| Total Production Copper Refined (t) | `PROD_COPPREFINED` | `PROD_COPPREFINED` |
| Total Production Crude Steel (t) | `PROD_CRUDESTEEL` | `PROD_CRUDESTEEL` |
| Total Production Diamonds (ct) | `PROD_DIAM` | `PROD_DIAM` |
| Total Production Ferro Chrome (t) | `PROD_FERROCHROME` | `PROD_FERROCHROME` |
| Total Production Gold (oz) | `PROD_GOLD` | `PROD_GOLD` |
| Total Production Gold Concentrate (oz) | `PROD_GOLDCON` | `PROD_GOLDCON` |
| Total Production Gold Smelting (t) | `PROD_GOLDSMELT` | `PROD_GOLDSMELT` |
| Total Production Hard Coking Coal (t) | `PROD_HARDCOAL` | `PROD_HARDCOAL` |
| Total Production Ilmenite (t) | `PROD_ILMENITE` | `PROD_ILMENITE` |
| Total Production Iron Ore (t) | `PROD_IRON` | `PROD_IRON` |
| Total Production Iron Ore Concentrate (t) | `PROD_IRONORECON` | `PROD_IRONORECON` |
| Total Production Lead (t) | `PROD_LEAD` | `PROD_LEAD` |
| Total Production Lead Concentrate (t) | `PROD_LEADCON` | `PROD_LEADCON` |
| Total Production Lead Smelting (t) | `PROD_LEADSMELT` | `PROD_LEADSMELT` |
| Total Production Manganese Alloy (t) | `PROD_MANGALLOY` | `PROD_MANGALLOY` |
| Total Production Manganese Ore (t) | `PROD_MANGORE` | `PROD_MANGORE` |
| Total Production Melt Shop (t) | `PROD_MELTSHOP` | `PROD_MELTSHOP` |
| Total Production Metallurgical Coal (t) | `PROD_MET` | `PROD_MET` |
| Total Production Molybdenum (t) | `PROD_MOLY` | `PROD_MOLY` |
| Total Production Nickel (t) | `PROD_NICK` | `PROD_NICK` |
| Total Production Nickel Concentrate (t) | `PROD_NICKCON` | `PROD_NICKCON` |
| Total Production Palladium (oz) | `PROD_PALLA` | `PROD_PALLA` |
| Total Production Pellets (t) | `PROD_PELLETS` | `PROD_PELLETS` |
| Total Production Platinum (oz) | `PROD_PLAT` | `PROD_PLAT` |
| Total Production Rhodium (oz) | `PROD_RHOD` | `PROD_RHOD` |
| Total Production Rutile (t) | `PROD_RUTILE` | `PROD_RUTILE` |
| Total Production Semi Soft Coking Coal (t) | `PROD_SEMISOFT` | `PROD_SEMISOFT` |
| Total Production Silver (oz) | `PROD_SILV` | `PROD_SILV` |
| Total Production Silver Concentrate (oz) | `PROD_SILVCON` | `PROD_SILVCON` |
| Total Production Silver Smelting (t) | `PROD_SILVSMELT` | `PROD_SILVSMELT` |
| Total Production Steel (t) | `PROD_STEEL` | `PROD_STEEL` |
| Total Production Sulphuric Acid _(flag: source_label_was_#NUM!)_ | `PROD_SULPHACID` | `PROD_SULPHACID` |
| Total Production Synthetic Rutile (t) | `PROD_SYNTHRUTILE` | `PROD_SYNTHRUTILE` |
| Total Production Thermal Coal (t) | `PROD_THERCOAL` | `PROD_THERCOAL` |
| Total Production Thermal Coal Export (t) | `PROD_THERCOALEPT` | `PROD_THERCOALEPT` |
| Total Production Titanium Dioxide (t) | `PROD_TIO2` | `PROD_TIO2` |
| Total Production Titanium (t) | `PROD_TITAN` | `PROD_TITAN` |
| Total Production Uranium (t) | `PROD_URAN` | `PROD_URAN` |
| Total Production Zinc (t) | `PROD_ZINC` | `PROD_ZINC` |
| Total Production Zinc Concentrate (t) | `PROD_ZINCCON` | `PROD_ZINCCON` |
| Total Production Zinc Smelting (t) | `PROD_ZINCSMELT` | `PROD_ZINCSMELT` |
| Total Production Zinc Refined (t) | `PROD_ZINCREFINED` | `PROD_ZINCREFINED` |
| Total Production Zircon (t) | `PROD_ZIRCON` | `PROD_ZIRCON` |

#### Mining — Other

| Label | Keyword | Norm |
|-------|---------|------|
| Realized Price _(flag: duplicate_with_oil)_ | `REAL_PRICE` | `REAL_PRICE` |
| Net Change in Cash | `CHG_CASH_CF` | `CHG_CASH_CF` |

### MLP

| Label | Keyword | Norm |
|-------|---------|------|
| Distributable Cash Flow | `DCF` | `DCF` |
| Distributable Cash Flow per Unit | `DCFPU` | `DCFPU` |
| Distributable Cash Flow to Limited Partners | `DCFLP` | `DCFLP` |
| Distributable Cash Flow per Unit to Limited Partners | `DCFPULP` | `DCFPULP` |

### Multi-Financial

| Label | Keyword | Norm |
|-------|---------|------|
| AUC - EOP (billions) | `AUC_EOP` | `AUC_EOP` |
| AUM - EOP (billions) | `AUM` | `AUM` |
| AUM - Average (billions) | `AUM_AVG` | `AUM_AVG` |
| Capital Deployment - AUM (billions) | `CAP_DPL_AUM` | `CAP_DPL_AUM` |
| Distributable Earnings - After Tax | `DISTR_EARN_ATAX` | `DISTR_EARN_ATAX` |
| Fee AUM - EOP (billions) | `FEE_AUM` | `FEE_AUM` |
| Fee Related Earnings | `FRE` | `FRE` |
| Fee-Related Earnings Per Share | `FREPS` | `FREPS` |
| Fee-Related Earnings - After Tax | `FEEREL_EARN_ATAX` | `FEEREL_EARN_ATAX` |
| Fee-Related Earnings Per Share - After Tax | `FREPS_ATAX` | `FREPS_ATAX` |
| Fee-Related Earnings Margin (%) | `FRE_MARG` | `FRE_MARG` |
| Fee Related Performance Income | `FEE_REL_PERF_INC` | `FEE_REL_PERF_INC` |
| Fee Related Revenues | `FEE_REL_REV` | `FEE_REL_REV` |
| Fundraising - AUM (billions) | `FDRAIS_AUM` | `FDRAIS_AUM` |
| Long Term Flows (billions) | `LT_FLOWS` | `LT_FLOWS` |
| Management Fee | `MGMT_FEE` | `MGMT_FEE` |
| Net Flows (billions) | `NETFLOWS` | `NETFLOWS` |
| Net Realized Performance Income | `NET_REALPERF_INC` | `NET_REALPERF_INC` |
| Performance-Related Earnings | `PERF_REAL_EARN` | `PERF_REAL_EARN` |
| Performance-Related Earnings Per Share _(flag: source_label_was_#NUM!)_ | `PERPS` | `PERPS` |
| Principal Investment Income | `PRIN_INV_INC` | `PRIN_INV_INC` |
| Principal Investment Income Per Share | `PRIN_INV_INC_PS` | `PRIN_INV_INC_PS` |
| Realizations - AUM (billions) | `REALZ_AUM` | `REALZ_AUM` |
| Realized Performance Income | `REAL_PERF_INC` | `REAL_PERF_INC` |
| Realized Performance Compensation | `REAL_PRF_COMP` | `REAL_PRF_COMP` |
| Spread-Related Earnings | `SPRD_REL_EARN` | `SPRD_REL_EARN` |
| Spread-Related Earnings Per Share | `SREPS` | `SREPS` |
| Transaction Fees | `TRANS_FEE` | `TRANS_FEE` |

### Oil & Gas

#### Oil & Gas — Segment Income

| Label | Keyword | Norm |
|-------|---------|------|
| Chemicals Income | `CHEM_OPINC` | `CHEM_OPINC` |
| Chemicals Post Taxes | `CHEM_NETINC` | `CHEM_NETINC` |
| Chemicals Income - Dom | `CHEM_DOM` | `CHEM_DOM` |
| Chemicals Post Taxes - Dom | `CHEM_NETINC_DOM` | `CHEM_NETINC_DOM` |
| Chemicals Income - Intl | `CHEM_INTL` | `CHEM_INTL` |
| Chemicals Post Taxes - Intl | `CHEM_NETINC_INTL` | `CHEM_NETINC_INTL` |
| Downstream Income | `R_M_OPINC` | `R_M_OPINC` |
| Downstream Post Taxes | `R_M_NETINC` | `R_M_NETINC` |
| Downstream Income - Dom | `R_M_DOM` | `R_M_DOM` |
| Downstream Post Taxes - Dom | `R_M_NETINC_DOM` | `R_M_NETINC_DOM` |
| Downstream Income - Intl | `R_M_INTL` | `R_M_INTL` |
| Downstream Post Taxes - Intl | `R_M_NETINC_INTL` | `R_M_NETINC_INTL` |
| Upstream Income | `E_P_OPINC` | `E_P_OPINC` |
| Upstream Post Taxes | `E_P_NETINC` | `E_P_NETINC` |
| Upstream Income - Dom | `E_P_DOM` | `E_P_DOM` |
| Upstream Post Taxes - Dom | `E_P_NETINC_DOM` | `E_P_NETINC_DOM` |
| Upstream Income - Intl _(flag: source_intl_op_vs_posttax_labels_appear_swapped)_ | `E_P_INTL` | `E_P_INTL` |
| Upstream Post Taxes - Intl _(flag: source_intl_op_vs_posttax_labels_appear_swapped)_ | `E_P_NETINC_INTL` | `E_P_NETINC_INTL` |

#### Oil & Gas — Benchmark Prices

| Label | Keyword | Norm |
|-------|---------|------|
| European Gas Price (mcf) | `PRICE_EUROGAS` | `PRICE_EUROGAS` |
| Henry Hub Price (mmbtu) | `PRICE_HENRYHUB` | `PRICE_HENRYHUB` |
| NYMEX Price (mmbtu) | `PRICE_NYMEX` | `PRICE_NYMEX` |
| Brent Price | `PRICE_BRENT` | `PRICE_BRENT` |
| Canadian Light Oil Price | `PRICE_CA_LIGHT` | `PRICE_CA_LIGHT` |
| Dubai Crude Price | `PRICE_DUBAI_OIL` | `PRICE_DUBAI_OIL` |
| Edmonton Par Oil Price | `PRICE_ED_OIL` | `PRICE_ED_OIL` |
| Synthetic Crude Price | `PRICE_SCO` | `PRICE_SCO` |
| Western Canadian Select Crude Price | `PRICE_WCS` | `PRICE_WCS` |
| West Texas Intermediate Price | `PRICE_WTI` | `PRICE_WTI` |
| Urals Crude Price | `PRICE_URALS` | `PRICE_URALS` |

#### Oil & Gas — Production Per Day

| Label | Keyword | Norm |
|-------|---------|------|
| Production Per Day (mboe/d) | `PRODPERDAY` | `PRODPERDAY` |
| Production Per Day - Oil & NGLs (mbbl/d) | `PROD_DAY_OIL_NGL` | `PROD_DAY_OIL_NGL` |
| Production Per Day - Natural Gas (mmcfe/d) | `PROD_DAY_GAS_ONLY` | `PROD_DAY_GAS_ONLY` |
| Production Per Day - NGLs (mbbl/d) | `PROD_DAY_NGL_ONLY` | `PROD_DAY_NGL_ONLY` |
| Production Per Day - Oil (mbbl/d) | `PROD_DAY_OIL_ONLY` | `PROD_DAY_OIL_ONLY` |
| Production Per Day - Gas & NGLs (mmcfe/d) | `PROD_DAY_GAS_NGL` | `PROD_DAY_GAS_NGL` |

#### Oil & Gas — Reserves

| Label | Keyword | Norm |
|-------|---------|------|
| 1P Reserves (mmboe) | `RSV_1P` | `RSV_1P` |
| 2P Reserves (mmboe) | `RSV_2P` | `RSV_2P` |
| 3P Reserves (mmboe) | `RSV_3P` | `RSV_3P` |

#### Oil & Gas — Realized Prices

| Label | Keyword | Norm |
|-------|---------|------|
| Realized Price _(flag: duplicate_with_mining)_ | `REAL_PRICE` | `REAL_PRICE` |
| Realized Price - Before Hedges | `REAL_PRICE_BH` | `REAL_PRICE_BH` |
| Realized Price - Gas & NGLs | `REALP_GAS_NGL` | `REALP_GAS_NGL` |
| Realized Price - Natural Gas | `REAL_PRICE_GAS` | `REAL_PRICE_GAS` |
| Realized Price - Natural Gas Before Hedges | `REALP_GAS_BH` | `REALP_GAS_BH` |
| Realized Price - NGLs | `REALP_NGL` | `REALP_NGL` |
| Realized Price - NGLs Before Hedges | `REALP_NGL_BH` | `REALP_NGL_BH` |
| Realized Price - Oil | `REAL_PRICE_Oil` | `REAL_PRICE_OIL` |
| Realized Price - Oil Before Hedges | `REALP_OIL_BH` | `REALP_OIL_BH` |
| Realized Price - Oil & NGLs | `REALP_OIL_NGL` | `REALP_OIL_NGL` |

#### Oil & Gas — Total Production

| Label | Keyword | Norm |
|-------|---------|------|
| Total Production - OIL (mmbbl) | `PROD_OIL` | `PROD_OIL` |
| Total Production - GAS (mmcf) | `PROD_GAS` | `PROD_GAS` |
| Total Production - NGL (mmbbl) | `PROD_NGL` | `PROD_NGL` |
| Total Production - OIL & NGL (mmbbl) | `PROD_OIL_NGL` | `PROD_OIL_NGL` |
| Total Production - OIL Sands (mmbbl) | `PROD_OIL_SANDS` | `PROD_OIL_SANDS` |
| Total Production _(flag: case_and_dup_with_mining_TOTAL_PROD)_ | `Total_PRod` | `TOTAL_PROD` |

#### Oil & Gas — Other

| Label | Keyword | Norm |
|-------|---------|------|
| DACF | `DACF` | `DACF` |
| Exploration Expense | `EXPL_EXP` | `EXPL_EXP` |
| OPEX per unit | `OPEX_UNIT` | `OPEX_UNIT` |

### Power & Utilities

| Label | Keyword | Norm |
|-------|---------|------|
| Cash Conversion (FCF/NetProfit) (%) | `CASH_CONV` | `CASH_CONV` |
| Deferred Income Taxes (CF) | `DFD_TAX_XITC_CF` | `DFD_TAX_XITC_CF` |
| Deferred Income Taxes - Assets (BS) | `DFD_TAX_DB` | `DFD_TAX_DB` |
| Deferred Income Taxes - Liabilities (BS) | `DFD_TAX_CR` | `DFD_TAX_CR` |
| Fuel | `FUEL` | `FUEL` |
| Fuel, Purchased Power | `FUEL_PURCH_POWER` | `FUEL_PURCH_POWER` |
| Purchased Power | `PURCH_POWER` | `PURCH_POWER` |
| Preferred Equity | `PFD_STK` | `PFD_STK` |
| Rate Base | `RATEBASE` | `RATEBASE` |
| Avg Rate Base | `AVGRATEBASE` | `AVGRATEBASE` |
| Taxes Other Than Income | `TAXES_NON_INC` | `TAXES_NON_INC` |
| Total Capacity (Mw) | `TOT_CAPACITY_MW` | `TOT_CAPACITY_MW` |
| Total Liabilities and Equity | `LIABS_SHLDRS_EQ` | `LIABS_SHLDRS_EQ` |

### Real Estate

| Label | Keyword | Norm |
|-------|---------|------|
| Acquisition NOI | `ACQUI_NOI` | `ACQUI_NOI` |
| Adjusted Funds from Operations (Per share) | `AFFO` | `AFFO` |
| Adjusted Funds From Operations (Gross) | `AFFO_GROSS` | `AFFO_GROSS` |
| AFFO Payout (%) | `AFFOPAYOUT_RATIO` | `AFFOPAYOUT_RATIO` |
| Real Estate Assets | `RE_ASSETS` | `RE_ASSETS` |
| Building and Improvement, Net | `BUILD_IMPROV` | `BUILD_IMPROV` |
| Cash NOI | `CASH_NOI` | `CASH_NOI` |
| Construction in Progress | `CONSTR_PROG` | `CONSTR_PROG` |
| Core Funds from Operations (Per share) | `CORE_FFO` | `CORE_FFO` |
| Core Funds From Operations (Gross) | `CORE_FFO_GROSS` | `CORE_FFO_GROSS` |
| Development | `DEV` | `DEV` |
| Development NOI | `DEV_NOI` | `DEV_NOI` |
| Disposition NOI | `DISPO_NOI` | `DISPO_NOI` |
| EPRA Net Tangible Assets (NTA) | `RE_EPRA_NTA` | `RE_EPRA_NTA` |
| EPRA Net Disposal Value (NDV) | `RE_EPRA_NDV` | `RE_EPRA_NDV` |
| EPRA Net Disposal Value (NDV) Per Share | `RE_EPRA_NDV_PS` | `RE_EPRA_NDV_PS` |
| EPRA Net Reinstatement Value (NRV) | `RE_EPRA_NRV` | `RE_EPRA_NRV` |
| EPRA Net Reinstatement Value (NRV) Per Share | `RE_EPRA_NRV_PS` | `RE_EPRA_NRV_PS` |
| EPRA Net Tangible Assets (NTA) Per Share | `RE_EPRA_NTA_PS` | `RE_EPRA_NTA_PS` |
| Funds from Operations (Per share) | `FFO` | `FFO` |
| Funds From Operations (Gross) | `FUNDS_OPER_GROSS` | `FUNDS_OPER_GROSS` |
| FFO Payout (%) | `FFOPAYOUT_RATIO` | `FFOPAYOUT_RATIO` |
| Gains/(Losses) on Sale of Real Estate | `GAIN_LOSS_SALE_RE` | `GAIN_LOSS_SALE_RE` |
| Implied Cap Rate (%) | `IMP_CAP_RATE` | `IMP_CAP_RATE` |
| Investment in Unconsolidated Entities | `INV_UNCON_ENTITY` | `INV_UNCON_ENTITY` |
| Development Properties | `DEVELOP_PROP` | `DEVELOP_PROP` |
| Investment Properties | `INVEST_PROP` | `INVEST_PROP` |
| Land | `LAND` | `LAND` |
| Land Held for Development | `LAND_HFD` | `LAND_HFD` |
| Loan to Value (%) | `LTV` | `LTV` |
| Real Estate Tax and Other | `RE_TAX` | `RE_TAX` |
| Reported Funds from Operations (Per share) | `FFO_REP` | `FFO_REP` |
| Reported Funds From Operations (Gross) | `FFO_REP_GROSS` | `FFO_REP_GROSS` |
| Same Store Revenue | `RE_SS_REV` | `RE_SS_REV` |
| Same Store Expense | `RE_SS_OPER_EXP` | `RE_SS_OPER_EXP` |
| Same Store Expense growth (%) | `SS_EXP_GR` | `SS_EXP_GR` |
| Same Store NOI | `SAME_STORE_NOI` | `SAME_STORE_NOI` |
| Real Estate Related Dep, Amort | `RE_DEPR_AMORT` | `RE_DEPR_AMORT` |
| Non-Real Estate Related Dep, Amort | `NONRE_DEPR_AMORT` | `NONRE_DEPR_AMORT` |
| Straight-line Rent | `STRAIGHTLINE_RENT` | `STRAIGHTLINE_RENT` |

### Retailers

| Label | Keyword | Norm |
|-------|---------|------|
| Net Sales per Retail Sq. Ft. | `SALES_RSF` | `SALES_RSF` |
| # Stores Closed During Period | `ST_CL` | `ST_CL` |
| # Stores Closed During Period - Dom. | `ST_CL_D` | `ST_CL_D` |
| # Stores Closed During Period - Intl. | `ST_CL_I` | `ST_CL_I` |
| # Stores Opened | `STOREN_OPENED` | `STOREN_OPENED` |
| # Stores Opened During Period - Dom. | `ST_OPN_D` | `ST_OPN_D` |
| # Stores Opened During Period - Intl. | `ST_OPN_I` | `ST_OPN_I` |
| # Stores at Period End | `ST_END` | `ST_END` |
| # Stores at Period End - Dom. | `ST_END_D` | `ST_END_D` |
| # Stores at Period End - Intl. | `ST_END_I` | `ST_END_I` |
| # Stores Relocated During Period | `ST_RLOC` | `ST_RLOC` |
| # Stores Relocated During Period - Dom. | `ST_RLOC_D` | `ST_RLOC_D` |
| # Stores Relocated During Period - Intl. | `ST_RLOC_I` | `ST_RLOC_I` |
| Same Store Sales Monthly (%) | `SAMESTORESALESM` | `SAMESTORESALESM` |
| Same Store Sales (%) | `SAMESTORESALES` | `SAMESTORESALES` |
| Same Store Sales - Dom. (%) | `SSS_D` | `SSS_D` |
| Same Store Sales - Intl. (%) | `SSS_I` | `SSS_I` |
| Selling Space Sq. Ft. (millions) | `SELL_SP` | `SELL_SP` |
| Selling Space Sq. Ft. (millions) - Dom. | `SELL_SP_D` | `SELL_SP_D` |
| Selling Space Sq. Ft. (millions) - Intl. | `SELL_SP_I` | `SELL_SP_I` |

### Telecoms

| Label | Keyword | Norm |
|-------|---------|------|
| Access Lines (thousands) | `ACCESS_LINES` | `ACCESS_LINES` |
| ARPU | `ARPU` | `ARPU` |
| Broadband ARPU | `BROAD_ARPU` | `BROAD_ARPU` |
| Broadband Subscribers (thousands) | `BROADBAND_SUB` | `BROADBAND_SUB` |
| Business HS Internet Subscribers (thousands) | `BUSIHSI_SUB` | `BUSIHSI_SUB` |
| Business Services ARPU | `BUSINESS_ARPU` | `BUSINESS_ARPU` |
| Business Services Subscribers (thousands) | `BUSI_SUB` | `BUSI_SUB` |
| Business Video Subscribers (thousands) | `BUSIVID_SUB` | `BUSIVID_SUB` |
| Business Voice Subscribers (thousands) | `BUSIVOIC_SUB` | `BUSIVOIC_SUB` |
| Churn (%) | `CHURN` | `CHURN` |
| Contribution Profit | `CONTR_PROF` | `CONTR_PROF` |
| Connected Devices Subscribers (thousands) | `DEVICES_SUB` | `DEVICES_SUB` |
| CPGA | `CPGA` | `CPGA` |
| Customer Relationship ARPU | `CUS_REL_ARPU` | `CUS_REL_ARPU` |
| Customer Relationship Subscribers (thousands) | `CUS_REL_SUB` | `CUS_REL_SUB` |
| Gross Adds (thousands) | `GROSS_ADDS` | `GROSS_ADDS` |
| High Speed Internet ARPU | `HIS_ARPU` | `HIS_ARPU` |
| High Speed Internet Subscribers (thousands) | `HS_INET_SUB` | `HS_INET_SUB` |
| Minutes of Usage | `MOU` | `MOU` |
| Monthly Revenue Per User | `M_REV_USER` | `M_REV_USER` |
| Mobile Phone Subscribers (thousands) | `MOBILE_SUB` | `MOBILE_SUB` |
| Net Adds (thousands) | `NET_ADDS` | `NET_ADDS` |
| Clients (thousands) | `SUBSCRIBERS_NB` | `SUBSCRIBERS_NB` |
| Paid Net Adds (thousands) | `PAIDNADDS` | `PAIDNADDS` |
| Postpaid Phone ARPU | `POSTPAID_PH_ARPU` | `POSTPAID_PH_ARPU` |
| Postpaid Phone Subscribers (thousands) | `POSTPHONE_SUB` | `POSTPHONE_SUB` |
| Postpaid Subscribers (thousands) | `POSTPAID_SUB` | `POSTPAID_SUB` |
| Prepaid Subscribers (thousands) | `PREPAID_SUB` | `PREPAID_SUB` |
| Residential Customer ARPU | `RESIDENT_ARPU` | `RESIDENT_ARPU` |
| Residential Data ARPU | `RESI_DATA_ARPU` | `RESI_DATA_ARPU` |
| Residential HS Internet Subscribers (thousands) | `RESIHSI_SUB` | `RESIHSI_SUB` |
| Residential Subscribers (thousands) | `RESI_SUB` | `RESI_SUB` |
| Residential Video ARPU | `RESI_VIDEO_ARPU` | `RESI_VIDEO_ARPU` |
| Residential Video Subscribers (thousands) | `RESIVID_SUB` | `RESIVID_SUB` |
| Residential Voice ARPU | `RESI_VOICE_ARPU` | `RESI_VOICE_ARPU` |
| Residential Voice Subscribers (thousands) | `RESIVOIC_SUB` | `RESIVOIC_SUB` |
| Retail Wireless ARPU | `RETAIL_ARPU` | `RETAIL_ARPU` |
| Security Subscribers (thousands) | `SECUR_SUB` | `SECUR_SUB` |
| SAC | `SAC` | `SAC` |
| Subscription Video ARPU | `SUBSVIDEO_ARPU` | `SUBSVIDEO_ARPU` |
| Video Advertising ARPU | `VIDEOADVERT_ARPU` | `VIDEOADVERT_ARPU` |
| Video ARPU | `VIDO_ARPU` | `VIDO_ARPU` |
| Video Subscribers (thousands) | `VIDO_SUB` | `VIDO_SUB` |
| Voice ARPU | `VOICE_ARPU` | `VOICE_ARPU` |
| Voice Subscribers (thousands) | `VOICE_SUB` | `VOICE_SUB` |
| Wholesale Wireless ARPU | `WHOLESAL_ARPU` | `WHOLESAL_ARPU` |
| Wholesale Subscribers (thousands) | `WHOLESAL_SUB` | `WHOLESAL_SUB` |
| Wireless ARPU | `WIRELES_ARPU` | `WIRELES_ARPU` |
| Wireless Subscribers (thousands) | `WIRELES_SUB` | `WIRELES_SUB` |
| Wireless Postpaid ARPU | `POSTPAID_ARPU` | `POSTPAID_ARPU` |
| Wireless Prepaid ARPU | `PREPAID_ARPU` | `PREPAID_ARPU` |
| Current RPO | `CURRENT_RPO` | `CURRENT_RPO` |
| Total RPO | `TOTAL_RPO` | `TOTAL_RPO` |
| Non Current RPO | `NON_CURRENT_RPO` | `NON_CURRENT_RPO` |
| Current RPO Bookings | `CURRENT_RPO_BOOKINGS` | `CURRENT_RPO_BOOKINGS` |
| Total RPO Bookings | `TOTAL_RPO_BOOKINGS` | `TOTAL_RPO_BOOKINGS` |

## Data quality flags

The source carries known label/casing artifacts. Keywords are stored with a normalized uppercase `norm` plus the original `keyword` (preserved).

| Keyword(s) | Issue |
|-----------|-------|
| `EBITDA` | Drop-down label in source reads 'EBITA' (typo); keyword and item label are EBITDA. |
| `EBITDAX` | Drop-down label reads 'EBITDAR' but keyword is EBITDAX. |
| `PROD_SULPHACID` | Item label lost in source (#NUM!); keyword valid. Restored label: Total Production Sulphuric Acid. |
| `PERPS` | Item label lost in source (#NUM!); keyword valid. Restored label: Performance-Related Earnings Per Share. |
| `REAL_PRICE` | Appears in both Mining and Oil sectors. Disambiguate by sector context. |
| `FFO` | Used as 'Funds from Operations' in estimate templates and in Real Estate item list. Same key, sector-context dependent. |
| `TOTAL_PROD, Total_PRod` | Near-duplicate; Mining=TOTAL_PROD, Oil=Total_PRod (mixed case). Normalize to uppercase but preserve original. |
| `Sales, REAL_PRICE_Oil` | Non-uppercase source keywords. FactSet keywords are generally case-insensitive; store normalized uppercase + original. |
| `E_P_INTL, E_P_NETINC_INTL` | Oil Upstream Intl op-income vs post-tax labels appear swapped vs the Dom pair. Verify against live FactSet. |

Notable cases: the **EBITDA** drop-down label reads 'EBITA' (typo) but the keyword/item is `EBITDA`; **REAL_PRICE** is duplicated across Mining and Oil & Gas (disambiguate by sector); mixed-case source keywords (`Sales`, `Total_PRod`, `REAL_PRICE_Oil`) are normalized to uppercase while the original is preserved.

