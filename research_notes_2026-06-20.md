# MSCI China Reversion/Fade Screen — Trade Notes

**Run date:** 20 June 2026 · **Data as of:** 18 June 2026 (2 trading days old — fresh)
**Universe:** MSCI China, 576 names · **Engine:** v2 (max_abs ranking, raw vol-z, leave-one-out peer classification, scored playbooks, RSI 35/65)
**Method:** Quantitative screen surfaces statistically dislocated, idiosyncratic names; each candidate then triaged with live catalyst research to separate *stock-specific & mean-reverting* from *event-driven / broken*.

> Educational / idea-generation only. Not investment advice. Verify all prices and filings independently before acting.

---

## Bottom line

| Name | Screen signal | Catalyst verdict | Action |
|---|---|---|---|
| **Far East Horizon (3360-HK)** | Oversold long, 1w z **−4.47**, RSI 18.5, peer-rel **−3.36** | Mechanical (ex-div + block sale), fundamentals intact | ✅ **Reversion long — highest conviction** |
| **Jiangxi Copper A (600362)** | Overbought fade, 1w z **+4.01**, peer-rel **+4.93** | Multi-catalyst, earnings-backed, commodity bid | ⛔ **Do NOT fade — trend intact** |
| **Xiamen Tungsten A (600549)** | Overbought fade, 1w z **+2.68**, RSI 77.6, peer-rel **+3.60** | Index-inclusion + theme-chase spike, above target | ✅ **Fade / take-profit candidate** |
| **Tsingtao Brewery A (600600)** | Oversold long, 1w z **−4.15**, RSI 20.9, peer-rel **−2.50** | Actually sector-wide (HK beer fell together) | ⚠️ **Pass — not truly idiosyncratic** |
| **New Hope Liuhe A (000876)** | Oversold long, 1w z −1.80 / 1m −3.37, RSI **11.5** | Hog-cycle trough, FY25 loss, dilution | ⛔ **Avoid — broken, not a dip** |

**Two actionable ideas:** long **Far East Horizon**; fade/trim **Xiamen Tungsten**. The screen's value showed up as much in what it *rejected* (New Hope, Jiangxi) as in what it surfaced.

---

## ✅ LONG — Far East Horizon (3360.HK) · Financials / Financial Services

**Reversion thesis — highest conviction.**

**The dislocation (screen):** 1-week z **−4.47** (the single most dislocated name in the book on a 1-week basis), RSI **18.5**, **−19%** below its 20-day mean, peer-relative z **−3.36** vs **84** financial-services peers → unambiguously **idiosyncratic**. This is the exact name the v2 peer fix was built to catch: it crashed alone while its sector did not.

**Why it fell — mechanical, not fundamental:**
- **Ex-dividend on 12 June** (HK$0.31 final, ~4% strip), then momentum selling carried it from ~HK$7.4 pre-ex-div to **HK$5.82** on 19 June — an overshoot well below the ex-div-adjusted level ([Futunn ex-div notice](https://news.futunn.com/en/post/67321425/far-east-horizon-03360-hk-plans-to-issue-us-400)).
- A small **UBS block sale** (3.0M shares @ HK$7.29, ~0.06% of float) on 5 June added pressure ([Zhitong via Futunn](https://www.futunn.com/en/stock/03360-HK)).
- An 18 June **US$4bn MTN programme renewal** was misread by some as dilution — it is a *routine annual debt shelf* ("no current intention to draw down the entire amount"), debt-only, not equity ([HKEX filing 18 Jun](https://www.hkexnews.hk/listedco/listconews/sehk/2026/0618/2026061801484.pdf)).

**Why it's not broken:**
- Q1 2026 revenue and net profit both up modestly YoY; inclusive-finance assets **+10% YoY**; NPL ratio edging down ([AAStocks Q1](http://www.aastocks.com/en/stocks/news/aafn-con/NOW.1517057/industry-news/hk6)).
- FY25 net profit +0.7% YoY; **payout ratio raised to 61%**; DPS +2% ([HKEX FY25 results](https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0311/2026031100161.pdf)).
- **9 Buy / 0 Sell**, consensus target **HK$9.02** (~55% above spot); ~6.5x TTM P/E, ~0.49x P/B ([Simply Wall St](https://simplywall.st/stocks/hk/diversified-financials/hkg-3360/far-east-horizon-shares)).
- ADB transition-finance loan signed 1 May — positive credit/ESG signal ([MarketScreener](https://www.marketscreener.com/quote/stock/FAR-EAST-HORIZON-LIMITED-7693170/news/?mode=pertinence)).

**Near-term catalyst:** **HK$0.31 cash dividend pays 29 June** — re-attracts yield buyers at a **~9.6% TTM yield** on the depressed price.

**Risks:** China credit-cycle / property spillover to leasing NPLs (not currently materializing); RMB pressure on USD bonds (US$300m due Oct-26, but market access is demonstrated via Jan-26 US$400m issue); industrial-operations segment still soft (FY25 revenue −5.2%).

**Setup:** Buy the dip expecting a snap-back toward the ex-div-adjusted level; the 29 June dividend is the proximate re-rating trigger. MACD still bearish — can scale in rather than chase the exact bottom.

---

## ✅ FADE / TAKE-PROFIT — Xiamen Tungsten (600549.SS) · Materials / Metals & Mining

**Overbought-fade thesis.**

**The dislocation (screen):** 1-week z **+2.68**, RSI **77.6**, **+38%** above its 20-day mean, peer-relative z **+3.60** vs **43** metals & mining peers → **idiosyncratic** overshoot (it ran far harder than the metals complex).

**Why it ran — and why most of it is not fundamentally new:**
- **+109% YTD, +34.8% in the single week** around 12–16 June.
- The legitimate driver (Q1 2026: **+189% net profit**, +238% tungsten-moly segment) was already in the price by April and is **fully captured in the sole analyst target of CNY 77.80** (CICC) ([research_fades.md, sourced]).
- The recent acceleration is **mechanical + thematic**: **SSE 180 index inclusion effective 12 June** (one-time passive buying, now complete) plus a 16-June limit-up swept in alongside **MLCC / rare-earth / AI themes** on an indirect dysprosium link — a classic three-themes-at-once retail momentum overshoot.

**Why fade:** At ~**CNY 85.9** the stock trades **~10% above** the consensus target that *already* bakes in record Q1 earnings; the passive index bid is done; **no fundamental catalyst until next earnings on 21 Aug**; downstream tungsten-powder prices have lagged concentrate, risking Q2 margin compression.

**Risks to the fade (size accordingly):** further China tungsten/rare-earth **export-control escalation** or an NdPr price breakout could re-ignite the trade; tungsten APT is structurally bid (China Feb-2025 export controls, strategic-mineral status from 15 June). This is a "cool-off / trim into strength," not a conviction short of a broken company.

---

## ⛔ DO NOT FADE — Jiangxi Copper A (600362.SS) · Materials / Metals & Mining

The screen's **most idiosyncratic overbought name** (1w z +4.01, peer-rel **+4.93**) — but catalyst research says **the rally is earned, not a spike to fade:**
- Q1 2026 net profit **+44% YoY**, operating cash flow **+888% YoY** (quality, not just price leverage).
- **JCC Copper Foil HKEX spin-off** (announced 30 Apr) on the AI-server HVLP copper-foil narrative; **SolGold/Cascabel acquisition** completed (4 Mar) adds a world-class porphyry.
- Copper at all-time highs into the **30 June US copper-tariff deadline**; 7 Buy / 0 Sell.

A-share is modestly above A-share consensus (~CNY 49), so there's *some* near-term profit-taking risk, but the multi-catalyst, earnings-backed thesis means this is **not a fade**. Good example of the screen flagging a stretched name that fundamentals justify.

---

## ⛔ AVOID — New Hope Liuhe A (000876.SZ) · Consumer Staples / Food Products

Screened as a deep oversold long (RSI **11.5**, the most extreme in the book), but it is a **broken near-term thesis, not a dip:**
- China's **hog-cycle trough**: May-26 hog price **RMB 9.48/kg (−35% YoY)** vs ~RMB 13–14 breakeven → producers losing ~RMB 280–380/head.
- **Q1 2026 net loss of RMB 898m** (vs +RMB 445m a year ago); FY25 loss RMB 1.5–1.8bn; **no dividend**; executing a **dilutive RMB 3.3bn private placement**.
- Analysts place the cycle bottom in **Q4 2026 – Q1 2027** at the earliest (sow inventory still above target, high frozen-pork stocks, summer demand slack).

Technically oversold, yes — but the fundamental warrant for near-term mean-reversion is absent. A reversion bet here is a *cycle-timing* bet, not a dislocation bet. **Skip until capacity clears.**

---

## ⚠️ PASS — Tsingtao Brewery A (600600.SS) · Consumer Staples / Beverages

A useful illustration of where the screen's tag needs human judgment. It flagged Tsingtao **idiosyncratic** (peer-rel −2.50 vs **10** beverage peers) — and within the *A-share beverage* group it did diverge. But the catalyst research shows the real driver was **sector-wide**: on **16 June all three HK-listed beer names fell together** (CR Beer −5.6%, Budweiser APAC −3.4%, Tsingtao −2.5%) on doubts that the 2026 World Cup will lift demand, plus a soft catering channel ([Moomoo 16 Jun](https://www.moomoo.com/news/post/71570901/hong-kong-market-movers-beer-stocks-decline-collectively-institutions-caution)).

Fundamentals are intact (Q1 net profit +5.2%, mix upgrade, margin expansion), but with the decline being a beer-complex de-rating rather than a stock-specific accident, conviction on a *clean idiosyncratic snap-back* is lower. **Pass for now**; revisit if Q2 volume data firms or it diverges from CR Beer / Budweiser. (Note for the screen: the A-share peer group missed the cross-listing read-through — a candidate refinement is to peer A-shares against their H-share complex where dual-listed.)

---

### Methodology footnotes
- **Idiosyncratic = peer-relative z**: a name's rank-z minus the leave-one-out median of its GICS sub-industry (rolled up to sector if the sub-industry has <3 peers). High |peer-rel z| = the move is its own, not the group's.
- **rank z (max_abs)**: the larger-magnitude of the 1-week and 1-month-ex-week vol-normalized z, sign preserved — so a violent week isn't diluted by a quiet month.
- **Event flags:** not available this run (event-date column not pulled), so catalysts were sourced from live news rather than the in-app calendar.
- All quantitative values are from the 18 June 2026 snapshot; all qualitative/catalyst claims are sourced inline above.
