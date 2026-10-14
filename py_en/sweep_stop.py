"""Joint sweep of stop-loss distance / trailing activation / holding period.

Background: the current initial_stop_min_atr=0.8 means ~84% of trades get stopped
out within 24 bars in practice, yet the median MFE for holding 24 bars is 2.65 ATR -
the stop is far smaller than the profit space.
Usage: python sweep_stop.py [--oos]
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


def ev(f_all, cfg, start, end):
    m = (f_all["time"] >= pd.Timestamp(start)) & (f_all["time"] < pd.Timestamp(end))
    fm = f_all[m].reset_index(drop=True)
    sig = SG.entry_scores(fm, cfg)
    r = BT.run(fm, cfg, sig, initial_capital=100000.0)
    mm = r.metrics
    if mm.get("交易次数", 0) < 20:
        return None
    yrs = (fm["time"].iloc[-1] - fm["time"].iloc[0]).days / 365.25
    n = mm["交易次数"]
    t = BT.trades_df(r.trades)
    hold = (pd.to_datetime(t["平仓时间"]) - pd.to_datetime(t["开仓时间"])).dt.total_seconds() / 3600
    return {"笔数": n, "次/周": round(n / (yrs * 52), 2), "胜率": mm["胜率"],
            "PF": mm["盈利因子"], "年化": mm["年化(CAGR)"], "回撤": mm["最大回撤"],
            "夏普": mm["夏普"], "R": mm["平均R倍数"], "持仓h": round(float(hold.median()), 1)}


def show(tag, r):
    if r is None:
        print(f"{tag:<52} insufficient sample")
        return
    print(f"{tag:<52} {r['笔数']:>4}trades {r['次/周']:>5.2f}/wk WR{r['胜率']:>5.1f}% "
          f"PF{r['PF']:>5.2f} CAGR{r['年化']:>8.2f}% DD{r['回撤']:>6.2f}% "
          f"Sharpe{r['夏普']:>5.2f} R{r['R']:>5.2f} hold{r['持仓h']:>5.1f}h")


def main():
    oos = "--oos" in sys.argv
    a, b = OOS if oos else IS
    print(f"=== Stop-loss / holding-period sweep {a} ~ {b} {'[out-of-sample]' if oos else '[in-sample]'} ===")
    base = load_config()
    h1 = GD.load_ohlc("XAUUSD", "H1", 20000, "mt5", cache_dir="data/cache")
    f0 = SG.prepare(h1, GD.resample(h1, "H4"), GD.resample(h1, "D1"), base)

    grid_stop = [2.0, 2.5, 3.0, 3.5]
    grid_act = [1.5, 2.5, 3.5]
    grid_hold = [0, 24, 48]
    res = []
    for meth in ("atr", "bollinger"):
        print(f"\n--- Trailing method {meth} ---")
        for ms_, act, mh in itertools.product(grid_stop, grid_act, grid_hold):
            c = copy.deepcopy(base)
            c["entry"]["min_score"] = 4
            c["exit"]["initial_stop_min_atr"] = ms_
            c["exit"]["trailing"]["method"] = meth
            c["exit"]["trailing"]["activate_atr"] = act
            c["exit"]["max_hold_bars"] = mh
            r = ev(f0, c, a, b)
            tag = f"stop={ms_:<4} act={act:<4} hold={mh:<3}"
            show(tag, r)
            if r:
                res.append((meth, ms_, act, mh, r))

    if res:
        # Robustness: require in-sample PF>=1.15 and drawdown<=25%
        good = [x for x in res if x[4]["PF"] >= 1.15 and x[4]["回撤"] <= 25]
        print(f"\n--- Robust zone (PF>=1.15 and DD<=25%): {len(good)} groups ---")
        for meth, ms_, act, mh, r in sorted(good, key=lambda x: -x[4]["夏普"])[:12]:
            show(f"{meth:<9} stop={ms_:<4} act={act:<4} hold={mh:<3}", r)


if __name__ == "__main__":
    main()
