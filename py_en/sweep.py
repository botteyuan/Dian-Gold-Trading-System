"""Relaxation sweep: find the balance point between trade frequency and profitability.

Usage: python sweep.py [--oos]
  Default in-sample 2023-06-01 ~ 2025-06-01
  --oos for out-of-sample 2025-06-01 ~ 2026-09-08
"""
from __future__ import annotations
import copy
import itertools
import os
import sys
import warnings

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

from gt.config import load_config
from gt import data as GD, signals as SG, backtest as BT

IS = ("2023-06-01", "2025-06-01")
OOS = ("2025-06-01", "2026-09-08")


def years_of(f):
    return (f["time"].iloc[-1] - f["time"].iloc[0]).days / 365.25


def eval_cfg(f_all, cfg, start, end):
    """Evaluate a configuration over a given date range. Returns a dict."""
    m = (f_all["time"] >= pd.Timestamp(start)) & (f_all["time"] < pd.Timestamp(end))
    fm = f_all[m].reset_index(drop=True)
    if len(fm) < 500:
        return None
    sig = SG.entry_scores(fm, cfg)
    r = BT.run(fm, cfg, sig, initial_capital=100000.0)
    mm = r.metrics
    if mm.get("交易次数", 0) < 5:
        return None
    yrs = years_of(fm)
    n = mm["交易次数"]
    return {
        "笔数": n,
        "次/周": round(n / (yrs * 52), 2),
        "胜率": mm["胜率"],
        "盈亏比": mm["风险报酬率(盈亏比)"],
        "PF": mm["盈利因子"],
        "年化": mm["年化(CAGR)"],
        "回撤": mm["最大回撤"],
        "夏普": mm["夏普"],
        "平均R": mm["平均R倍数"],
    }


def show(tag, r):
    if r is None:
        print(f"{tag:<46} insufficient sample")
        return
    print(f"{tag:<46} {r['笔数']:>4}trades {r['次/周']:>5.2f}/wk  "
          f"WR{r['胜率']:>5.1f}% PF{r['PF']:>5.2f} CAGR{r['年化']:>6.2f}% "
          f"DD{r['回撤']:>5.2f}% Sharpe{r['夏普']:>5.2f} R{r['平均R']:>5.2f}")


def main():
    oos = "--oos" in sys.argv
    a, b = OOS if oos else IS
    print(f"=== Window {a} ~ {b} {'[out-of-sample]' if oos else '[in-sample]'} ===")

    base = load_config()
    h1 = GD.load_ohlc("XAUUSD", "H1", 20000, "mt5", cache_dir="data/cache")
    h4 = GD.resample(h1, "H4")
    d1 = GD.resample(h1, "D1")

    # ---------- Group 1: min_score x require_pullback (no indicator recompute needed) ----------
    print("\n--- Group 1: min_score x require_pullback ---")
    f0 = SG.prepare(h1, h4, d1, base)
    for ms, rp in itertools.product([5, 4, 3], [True, False]):
        c = copy.deepcopy(base)
        c["entry"]["min_score"] = ms
        c["entry"]["require_pullback"] = rp
        show(f"min_score={ms} require_pullback={rp}", eval_cfg(f0, c, a, b))

    # ---------- Group 2: single-factor relaxation (requires indicator recompute) ----------
    print("\n--- Group 2: single-factor relaxation (baseline min_score=4, pullback=True) ---")
    variants = {
        "baseline(min4)": {},
        "level_proximity 0.35->0.50": {"level_proximity_atr": 0.50},
        "level_proximity 0.35->0.70": {"level_proximity_atr": 0.70},
        "stoch 20/80->25/75": {"stochastic": {"oversold": 25, "overbought": 75}},
        "stoch 20/80->30/70": {"stochastic": {"oversold": 30, "overbought": 70}},
        "guppy pullback 0.60->0.80": {"guppy": {"pullback_atr_ratio": 0.80}},
        "guppy pullback 0.60->1.00": {"guppy": {"pullback_atr_ratio": 1.00}},
        "candle body 0.60->0.75": {"candle": {"small_body_ratio": 0.75}},
        "candle body 0.60->0.90": {"candle": {"small_body_ratio": 0.90}},
        "squeeze pct 0.25->0.35": {"bollinger": {"squeeze_percentile": 0.35}},
        "squeeze pct 0.25->0.45": {"bollinger": {"squeeze_percentile": 0.45}},
    }
    cache_f = {}
    for name, patch in variants.items():
        c = copy.deepcopy(base)
        c["entry"]["min_score"] = 4
        for k, v in patch.items():
            if isinstance(v, dict) and k in c:
                c[k].update(v)
            else:
                c[k] = v
        key = repr(sorted(patch.items()))
        if key not in cache_f:
            cache_f[key] = SG.prepare(h1, h4, d1, c)
        show(name, eval_cfg(cache_f[key], c, a, b))


if __name__ == "__main__":
    main()
