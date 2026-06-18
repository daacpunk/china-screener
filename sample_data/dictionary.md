# FactSet FQL Price-Series Dictionary (sample)

This wiki documents the FQL formulas used by the **Formula Generator (Tab 2)**
to pull clean daily price/volume time series and point-in-time reference data
out of FactSet via the Excel `=FDS(...)` function.

> **Indicators (RSI, MACD, z-scores) are NOT pulled from FactSet.** They are
> computed inside this app (Tab 3) from the uploaded price/volume series.

## Formula index

| Key | Label | FQL template |
|-----|-------|--------------|
| `price` | Daily closing price | `P_PRICE({start}:{end}:{freq})` |
| `volume` | Daily volume | `P_VOLUME({start}:{end}:{freq})` |
| `adv_usd_20d` | 20-day average daily value traded (USD) | `P_ADV_USD(20,{end})` |
| `sector` | GICS sector (point-in-time) | `FG_GICS_SECTOR({end})` |
| `sub_industry` | GICS sub-industry (point-in-time) | `FG_GICS_SUB({end})` |
| `index_weight` | Index weight in benchmark | `FG_INDEX_WEIGHT(#MSCI_CHINA,{end})` |
| `next_earnings` | Next earnings/event date | `FE_EVENT_DATE(EARNINGS,NEXT)` |

## Placeholders

- `{start}` / `{end}` — relative (`-2Y`, `0D`) or explicit dates (`20240101`).
- `{freq}` — `D` daily (used throughout this screen).

## Method A — time-series block (preferred)

Mirrors FactSet *Insert Formula → Closing Price, Daily, range −2Y*. One FDS
formula per series spills a full date+price+volume block downward.

## Method B — offset grid (fallback)

Generic relative-offset pattern using the template root, e.g.
`=FDS($A$2,"P_PRICE(-"&(ROW()-3)&"D)")`, or explicit dates in column B via
`=FDS($A$2,"P_PRICE("&B2&")")`.
