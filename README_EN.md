# Dina Gold Trading System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
📘 **中文版 / Chinese version**: [README.md](README.md)

One-liner: **Python drives the fundamental bias & backtesting; MT5 handles execution.**

> Fundamental analysis assumes the market is always wrong; technical analysis assumes the market is always right.
> — These two methods are对立统一 (dialectically unified) and must not be mixed.

---

## 1. System Overview (Optimized System)

```
                      ┌─────────────────────────────────────────────┐
   Driver Analysis    │  Monetary : Geo-politics / Economic growth    │
   (Fundamentals)     │  Investment: Real rate / Capital flows       │ ─┐ gold_signal.ini
   Python daily       │  Commodity : Jewelry / Industrial / CB buy   │  │ (bias/veto/size/kelly)
                      └──────────────────┬──────────────────────────┘  │
                                         │ bias + D1 trend             │
                                         ▼                            │
   ┌──────────────────────────────────────────────────────────┐ │
   │  B3 Long/Short Regime Framework (core optimization)       │ │
   │  Fundamental bias × D1 trend tri-state → direction & skew │ ◄┘
   └──────────────────────────┬───────────────────────────────┘
                              │
                      ┌───────▼──────────────────────────────────┐
   Behavioral Analysis │  Trend = Guppy MA: cross(warn)→pullback    │ ─→ market order
   (Technical)         │  Level = Pivot + Fibonacci: proximity      │
   MT5 EA per H1       │  State = BB squeeze·divergence + candle    │
                      └─────────────────────────────────────────┘
```

**Core of this optimization**: the **B3 long/short Regime framework**. The system is no longer a simple long‑only —
the technical five‑conditions remain the *only* entry trigger, but **direction and position sizing are jointly decided by
"fundamental bias × daily trend"**. Both live trading and backtesting use the B3口径 (caliber); shorts are only released
by the regime when the fundamental bias is short (bias<0), which彻底 (thoroughly) fixes the mismatch of
"pretty backtest in a bull market, bleeding live account in a bear market".

---

## 2. Trading Logic

### Entry (Trend / Level / State — all three must align)

**1‑hour chart · Five Conditions** (default: at least 3 satisfied, pullback mandatory)

| # | Condition | Tool | Meaning |
|---|-----------|------|---------|
| ① | **Pullback** *[mandatory]* | Guppy (GMMA) 6+6 EMAs | After a cross, short‑term group hugs but does not pierce the long‑term group = trend confirmation |
| ② | **Squeeze [Divergence]** | Bollinger(13, 0, 1.618) | Meso convergence/divergence node; long near lower band / short near upper band is better |
| ③ | **Exhaustion** | Stochastic (5,3,3) | Falling after overbought / rising after oversold |
| ④ | **Proximity** | Fibonacci retr.+ext. ∪ Pivot | Price arrives (distance ≤ 0.35×ATR) |
| ⑤ | **Shrinking** | Candle convergence | Small body / long wick / doji, with wicks gradually shortening |

All five aligned → **confirm on the signal candle's close → enter at the next candle's open**.

**4‑hour chart · Three Patterns** (must "appear on the Bollinger band track"): bullish/bearish engulfing · morning/evening star · piercing/dark‑cloud‑cover.
> Evidence (2023‑2026 bull‑market backtest): 4H resonance adds no edge and even hurts the long‑only system, so `InpH4Resonance=false` by default — the pure‑1H optimal system is kept.

### Exit (Dina's Three Laws: always stop‑loss, never take‑profit, use trailing stop)

| Situation | Trigger | Action |
|-----------|---------|--------|
| Initial stop | Beyond a valid key level + 0.30×ATR buffer | Full stop |
| After a large move | Close breaks the outer Bollinger band | Reduce 50%, move stop to cost |
| After a small move | Close re‑crosses the Bollinger mid | **Off by default** (re‑crossing the mid washes out trend profit; the typical real‑world "stop‑hunted" root cause) |
| Throughout the trade | Mid / ATR trailing stop (after floating profit ≥ 2.5×ATR) | Let the remainder run |
| Reverse entry signal | Opposite five‑conditions / three‑pattern appears | Close |

---

## 3. B3 Long/Short Regime Framework (Core Optimization)

**Inputs**: `bias` ∈ {+1 long / 0 neutral / −1 short} (from Python fundamental driver analysis) × `d1_trend` ∈ {+1 clearly up / 0 unclear / −1 clearly down} (daily EMA50 + ATR bandwidth gate).

**Rule matrix** (config.yaml `entry.regime_*` and EA `DinaRegimeGate` are strictly consistent):

| Fundamental bias | D1 trend | Decision | Long factor | Short factor |
|-----------------|----------|----------|------------|-------------|
| Short (−1) | Clearly down | **Short only** | 0 | 1.0 |
| Short (−1) | Unclear | **Both, short>long** | 0.40 | 1.0 |
| Long (+1) | Clearly up | **Long only** | 1.0 | 0 |
| Long (+1) | Unclear | **Both, long>short** | 1.0 | 0.40 |
| Neutral (0) | Directional | **Long only** | 1.0 | 0 |
| Neutral (0) | Unclear | **Stand aside (no trade)** | 0 | 0 |

- `regime_skew_factor = 0.40`: position factor of the non‑dominant direction; the dominant direction is always 1.0.
- **B3 core**: Neutral + no D1 trend → stand aside, eliminating the "neutral‑flat" historical loss bracket (the drag bracket with full‑sample PF<1).
- If the signal file is stale (>24h unrefreshed) → conservatively fall back to long‑only, avoiding "yesterday's bias vetoing today's real signal".
- Short master safety lock `InpAllowShort=true`: only the master switch to allow shorts; the concrete long/short is still decided by the regime matrix.

---

## 4. Directory Structure

```
gold-trader/
├─ README.md                 (this Chinese doc)
├─ README_EN.md              English documentation
├─ LICENSE                   MIT License
├─ .gitignore
├─ config/config.yaml        All parameters (indicators/entry/regime/risk/driver weights/data sources)
├─ run.bat / start_gold_daemon.bat / stop_gold_daemon.bat   run/daemon scripts
├─ py/
│  ├─ run_daily.py           Main entry: data→signals→fundamentals→baseline backtest→report→signal file
│  ├─ backtest_full.py       B3 full‑sample backtest (live caliber, 2021-2026 incl. bear market)
│  ├─ validate_regime.py     regime A/B/B2/B3 comparison validation
│  ├─ sweep.py / sweep_exit.py / sweep_stop.py   param tools (entry/exit/stop)
│  ├─ requirements.txt
│  └─ gt/
│     ├─ data.py             MT5 / yfinance / CSV quotes + FRED macro (with cache)
│     ├─ indicators.py       Bollinger, Guppy, Stochastic, swing points, Fibonacci, pivots, candle patterns
│     ├─ signals.py          Five‑condition scoring, 4H three patterns, initial stop
│     ├─ fundamental.py      Seven‑factor driver analysis + historical bias reconstruction
│     ├─ backtest.py         B3 backtest engine (regime gate / scale‑down / trailing / metrics)
│     ├─ analytics.py        Seasonality, session, convergence stats, condition attribution, forward performance
│     ├─ report.py           HTML report + gold_signal.ini export
│     └─ config.py / goldorg.py
├─ mql5/
│  ├─ Experts/DinaGoldTrader.mq5        EA (with B3 gate + colored GUI panel)
│  ├─ Indicators/DinaGuppy.mq5(.ex5)    Guppy composite MA indicator
│  └─ Include/DinaGold/*.mqh            indicator/pattern/signal/trade/fundamental modules
│                                         (DinaFundamental.mqh contains DinaRegimeGate)
├─ data/cache/                 quote cache (parquet)
└─ output/                     report.html / gold_signal.ini / run_daily.log
                                backtest_full.md / backtest_full_equity.csv
                                regime_validation.md
```

---

## 5. Installation

### 1. Python side

```bash
cd gold-trader/py
pip install -r requirements.txt
# Extra install when MT5 data fetching is needed: pip install MetaTrader5
```

### 2. MT5 side

Copy the three locations under `mql5/` into the corresponding terminal directories:

```
mql5/Include/DinaGold/*   →  <MT5>/MQL5/Include/DinaGold/
mql5/Experts/*.mq5        →  <MT5>/MQL5/Experts/
mql5/Indicators/*.mq5     →  <MT5>/MQL5/Indicators/
```

Compile in MetaEditor (F7). On the local machine IC Markets MT5 is installed; the above files are already copied and compiled.

---

## 6. Daily Run

```bash
# Full pipeline: fetch → indicators → driver analysis → baseline backtest → report → MT5 signal file
python run_daily.py

# Write the signal into MT5's Files directory (EA auto‑reads & refreshes every 60 min)
# Replace the path below with your own MT5 install directory:
python run_daily.py --mt5-files "<your MT5 install dir>/MQL5/Files"

# Specify data source / offline / local CSV
python run_daily.py --source mt5
python run_daily.py --offline
python run_daily.py --csv data/XAUUSD_H1.csv

# B3 full‑sample backtest (live caliber, 2021-2026, incl. 2022 bear) — no MT5 needed
python backtest_full.py
```

Artifacts:
- `output/report.html` — daily report: driver analysis, technical status, baseline backtest metrics, condition attribution, forward performance
- `output/gold_signal.ini` — fundamental bias, D1 trend, Kelly f*, key levels, factor details for the EA
- `output/backtest_full.md` / `backtest_full_equity.csv` — B3 live‑caliber backtest report & equity curve

> **Caliber note**: the "main backtest" in `run_daily.py` is a **pure‑technical long‑only baseline** (`bias=0`,
> to isolate the technical system itself); **the live B3 real caliber is in `backtest_full.py`**.
> Do NOT mistake the daily report's backtest numbers for live performance.

### Chart Panel (colored GUI)

The EA draws a colored panel with `OBJ_LABEL` at the top‑left of the chart (red up / green down), refreshed every 2 seconds (also shown when market is closed): **signal time/freshness, driver score, bias, D1 trend, Regime gate & position skew, veto status, size factor, Kelly, technical five‑condition snapshot**. Drag the `DinaGuppy` indicator onto the H1 chart to visually verify "cross → pullback".

---

## 7. EA Parameters (B3 version)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `InpAllowTrade` | **true** | Set `false` first to observe signals for a while; enable after confirmation |
| `InpMinScore` | 3 | Minimum five‑conditions satisfied (pullback mandatory + any two of the rest) |
| `InpMinStopATR` | 3.00 | **Most critical**. Minimum stop distance; old value 0.8 got 84% of trades stopped before profit |
| `InpTrailMethod` | 1 | 0=BB mid 1=ATR pullback (1实测 better) |
| `InpTrailActivate` | 2.50 | Trailing starts only after floating profit reaches this ATR; too early sweeps early winners |
| `InpMaxHoldBars` | 24 | Max holding candles, 0=unlimited |
| `InpAllowShort` | **true** | Short master safety lock; concrete long/short decided by B3 regime matrix |
| `InpSkewFactor` | 0.40 | Position factor of non‑dominant direction (dominant=1.0) |
| `InpNeutralFlatAside` | true | Neutral + no D1 trend → stand aside (B3 adopted) |
| `InpH4Resonance` | false | 4H & 1H resonance (AND); off by default (empirically weakens long edge) |
| `InpRiskPct` | 1.0 | Per‑trade risk % of equity |
| `InpUseKelly` | true | Use Python‑side half‑Kelly f* (capped: per‑trade risk ≤ 3% equity) |
| `InpMaxSpreadPts` | 60 | Spread filter |
| `InpSignalFile` | gold_signal.ini | Placed in `<MT5>/MQL5/Files/` |
| `InpMaxSignalAgeHours` | 24 | Signal file staleness threshold; beyond this fall back to conservative long‑only |
| `InpLotMode` | 0 (LOT_RISK) | Lot‑sizing mode: 0=risk% mode (InpRiskPct+half‑Kelly) / 1=fixed lots (InpFixedLots) / 2=ATR‑equalized fixed‑risk% (InpRiskPct as per‑trade risk%) |
| `InpFixedLots` | 0.1 | Fixed lots per trade (only when InpLotMode=1) |

> **Three lot‑sizing modes (`InpLotMode`)**:
> - `LOT_RISK=0` (default): per‑trade risk = `InpRiskPct`% of equity, times half‑Kelly f* and fundamental `size_mult`; long×1.0 / short×0.4.
> - `LOT_FIXED=1`: fixed `InpFixedLots` lots per trade, still scaled by the regime long/short skew (long×1.0 / short×0.4); ignores risk%/Kelly/fundamental.
> - `LOT_ATR_RISK=2`: per‑trade risk fixed at `InpRiskPct`% of equity, lot derived inversely from the stop's ATR distance (scale down when volatile, up when calm); ignores Kelly/fundamental, keeps only the long/short skew; leverage adapts to volatility.

---

## 8. Fundamentals Do Only Three Things

Per the book's positioning, driver analysis is **not** an entry trigger; it only:

1. **Directional bias** — seven‑factor weighted total score; `|score| ≥ 2.0` produces a directional bias (long/short/neutral)
2. **Position scaling** — `size_mult` scaled by bias strength; amplifies when consistent with position direction, shrinks when opposite
3. **Signal staleness detection** — if stale, B3 falls back to long‑only, avoiding using expired bias to kill today's signal

> Note: `veto_enabled` is off by default — the directional‑veto responsibility is now carried by the B3 regime matrix
> (when bias flips short, the regime directly forbids long / releases short), no longer a separate "hard veto" switch.

Seven‑factor weights (config.yaml) and logic layers:

| Layer | Factor | Weight |
|-------|--------|--------|
| Monetary | Geo‑politics / Economic growth / CB buying | 2.0 / 1.0 / 1.5 |
| Investment | Real rate (highest weight) / Capital flows | 2.5 / 1.5 |
| Commodity | Jewelry demand / Industrial use | 0.8 / 0.5 |

The three items that cannot be auto‑fetched (CB buying, jewelry/industrial quarterly data) are hand‑filled in `config.yaml → fundamental.manual`, range −2…+2.

---

## 9. Backtest Performance (B3 Production Caliber, 2021‑2026 Full Sample)

Data window **2020‑12‑31 ~ 2026‑09‑25** (H1 33917 bars, incl. 2022 rate‑shock bear, 2023‑2025 bull, 2026 down leg).
Initial $100k, 30‑pt spread, 1.0% per‑trade risk, half‑Kelly capped at 3%.

### Overview Comparison (A pure‑long / B original / B2 fix / B3 adopted)

| Metric | A pure‑long | B original | B2 fix | **B3 adopted** |
| --- | --- | --- | --- | --- |
| Trades | 689 | 1141 | 928 | **864** |
| Win% | 53.99 | 51.45 | 53.45 | **54.17** |
| Profit Factor | 1.08 | 1.05 | 1.14 | **1.21** |
| Total Return% | 28.47 | 29.45 | 63.38 | **91.84** |
| CAGR% | 4.47 | 4.60 | 8.94 | **12.03** |
| Max Drawdown% | 33.18 | 28.33 | 28.93 | **22.13** |
| Sharpe | 0.31 | 0.30 | 0.54 | **0.72** |

**B3 beats pure‑long A on all four of PF / CAGR / Drawdown / Sharpe**, and beats B2 (the lift from "neutral‑flat stands aside").

### By Year (B3 caliber)

| Year | Trades | PF | CAGR% | Max DD% |
|------|--------|-----|-------|---------|
| 2021 | 146 | 0.94 | -4.88 | 17.41 |
| 2022 | 174 | 0.96 | -2.88 | 10.64 |
| 2023 | 171 | 1.22 | 16.75 | 12.63 |
| 2024 | 132 | 1.21 | 14.37 | 14.87 |
| 2025 | 140 | 1.60 | 40.45 | 7.10 |
| 2026 | 101 | 1.22 | 14.42 | 7.53 |

**Framework value**: down years (2021/2022/2026) clearly cut losses vs pure‑long; up years (2023‑2025) roughly持平 (hold even) — it trades "lose less in headwinds" for higher Sharpe, not chasing bull runs. Shorts only make money when the fundamental is short (`空|空偏*` brackets PF mostly ≥1), confirming shorts are directioned by fundamentals and must not be abused.

### Three Lot‑Sizing Modes Compared (B3 caliber; returns/DD/Sharpe are capital‑independent)

| Lot mode | Total% | CAGR% | Max DD% | Sharpe | PF | Exp./trade |
| --- | --- | --- | --- | --- | --- | --- |
| Fixed 0.1 lot (LOT_FIXED) | +177.8 | 19.5 | 28.9 | 0.68 | 1.20 | $13.9 |
| ATR risk 1% (LOT_ATR_RISK, InpRiskPct=1.0) | +91.9 | 12.0 | 22.1 | 0.72 | 1.21 | $7.2 |
| ATR risk 2% (LOT_ATR_RISK, InpRiskPct=2.0) | +228.3 | 23.0 | 41.6 | 0.72 | 1.22 | $18.1 |

> Note: ATR modes are **volatility‑targeting** (scale down when volatile, up when calm) — counter‑cyclical de‑leveraging; the fixed 0.1‑lot mode is **pro‑cyclical** (wider ATR → larger per‑trade risk → adds size in turbulent periods), hence its larger drawdown. 1% and 2% share the same Sharpe (proportional leverage doesn't change Sharpe) but both beat the fixed‑lot 0.68; pick ATR 1% for stability, ATR 2% for growth.

---

## 10. Live Validation (MT5 Account Trade‑History Report Audit)

Line‑by‑line reconciliation of `ReportHistory-52922209.html` (2026‑09‑30 ~ 10‑02, demo ICMarketsSC‑Demo):

- Opening balance 6602.46 → closing 6817.61, diff 215.15 = total net profit; Profit Factor 11.85 = gross profit 234.98 / |gross loss 19.83| — **balance reconciliation holds, no fabrication**.
- **Live EA correctly runs B3**: short 0.03 / long 0.01 ≈ 3×, exactly matching `DinaRegimeGate`'s short‑bias+no‑trend branch (`longSkew=0.40`, `shortSkew=1.0`, plus shorts have tighter stops); shorts at full size recently profited big (75.39 + 158.13), longs at reduced size only small losses.
- All deal tickets paired, no external/manual trades — all EA‑automated.

> Note: that weekly report is only 3 days / 5 trades + 1 floating‑loss position; PF 11.85 is a lucky value from "caught the 9.30‑10.2 short move + tiny gross loss" and **must not be extrapolated** to the long term.

---

## 11. Risk Warnings

- Backtest excludes slippage, swap, and some brokers' floating spreads; live trading will decay.
- Set `InpAllowTrade=false` first to observe; go live only after signals match your discretionary judgment.
- Dina's Third Law: **must stop‑loss, cannot take‑profit**. Any "take profit when ahead" manual intervention destroys the system's expectation.
- Historical bias limitation: only INDPRO + DFII10 two macro factors (sandbox CBOE VIX unreachable, loses "geo‑politics" item), short days skew more; the system is positioned as a relative signal of "shorts work when bias flips short", not an absolute predictor.
- Backtest counts 30 pts/trade (~0.054R). The higher the trade frequency, the larger the cost share — a real trade‑off between "opportunities" and "profit".
- B3 can still misjudge (e.g. `空|多偏*` brackets PF<1 in a long‑biased environment); regime is a probabilistic framework, not a holy grail.

---

## 12. License & Disclaimer

### License
This project is open‑sourced under the **MIT License** — see [LICENSE](LICENSE).

### Disclaimer
- This project is for **education and research only**; it is not investment advice or an offer.
- Live trading carries risk of principal loss; please validate thoroughly on a demo account before considering live.
- The author and contributors are not liable for any profit or loss arising from the use of this system.
- Historical backtest performance does not represent future returns; the regime framework is a probabilistic tool, not a holy grail.
