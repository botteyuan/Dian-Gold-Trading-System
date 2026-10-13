"""Exit-rule grid sweep: after correcting look-ahead bias, re-find profitable exit combinations.

Usage: python sweep_exit.py [--oos]
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
    if len(fm) < 500:
        return None
    sig = SG.entry_scores(fm, cfg)
    r = BT.run(fm, cfg, sig, initial_capital=100000.0)
    mm = r.metrics
    if mm.get("交易次数", 0) < 5:
        return None
    yrs = (fm["time"].iloc[-1] - fm["time"].iloc[0]).days / 365.25
    n = mm["交易次数"]
    return {"笔数": n, "次/周": round(n / (yrs * 52), 2), "胜率": mm["胜率"],
            "PF": mm["盈利因子"], "年化": mm["年化(CAGR)"], "回撤": mm["最大回撤"],
            "夏普": mm["夏普"], "R": mm["平均R倍数"]}


def show(tag, r):
    if r is None:
        print(f"{tag:<58} 样本不足")
        return
    print(f"{tag:<58} {r['笔数']:>4}笔 {r['次/周']:>5.2f}/周 胜{r['胜率']:>5.1f}% "
          f"PF{r['PF']:>5.2f} 年化{r['年化']:>7.2f}% 撤{r['回撤']:>6.2f}% "
          f"夏普{r['夏普']:>5.2f} R{r['R']:>5.2f}")


def main():
    oos = "--oos" in sys.argv
    a, b = OOS if oos else IS
    print(f"=== 出场网格 {a} ~ {b} {'[样本外]' if oos else '[样本内]'} ===")
    base = load_config()
    h1 = GD.load_ohlc("XAUUSD", "H1", 20000, "mt5", cache_dir="data/cache")
    f0 = SG.prepare(h1, GD.resample(h1, "H4"), GD.resample(h1, "D1"), base)

    grid = {
        "trailing.method": ["bollinger", "atr"],
        "trailing.activate_atr": [1.0, 2.0, 3.0],
        "close_beyond_middle": [True, False],
        "reverse_signal_close": [True, False],
    }
    print("\n--- 出场规则网格（min_score=4）---")
    res = []
    for meth, act, cbm, rsc in itertools.product(
            grid["trailing.method"], grid["trailing.activate_atr"],
            grid["close_beyond_middle"], grid["reverse_signal_close"]):
        c = copy.deepcopy(base)
        c["entry"]["min_score"] = 4
        c["exit"]["trailing"]["method"] = meth
        c["exit"]["trailing"]["activate_atr"] = act
        c["exit"]["close_beyond_middle"] = cbm
        c["exit"]["reverse_signal_close"] = rsc
        r = ev(f0, c, a, b)
        tag = f"{meth:<9} act={act:<3} 中轨出={str(cbm):<5} 反手={str(rsc):<5}"
        show(tag, r)
        if r:
            res.append((tag, r))

    if res:
        print("\n--- 按 PF 排序 Top 8 ---")
        for tag, r in sorted(res, key=lambda x: -x[1]["PF"])[:8]:
            show(tag, r)


if __name__ == "__main__":
    main()
