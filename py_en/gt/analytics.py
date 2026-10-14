"""Historical data analysis: seasonality, sessions, convergence stats, five-condition attribution."""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def seasonality(f: pd.DataFrame, horizon: int = 12) -> Dict[str, pd.DataFrame]:
    """Returns after `horizon` bars, grouped by month / weekday / hour."""
    d = f[["time", "close"]].copy()
    fut = d["close"].shift(-horizon) / d["close"] - 1.0
    d["ret"] = fut
    d["month"] = d["time"].dt.month
    d["dow"] = d["time"].dt.dayofweek
    d["hour"] = d["time"].dt.hour
    out = {}
    for key, name in (("month", "月份"), ("dow", "星期"), ("hour", "小时(GMT)")):
        g = d.groupby(key)["ret"].agg(["mean", "std", "count"])
        g["胜率"] = d.assign(w=d["ret"] > 0).groupby(key)["w"].mean()
        g.columns = ["平均收益", "波动", "样本数", "胜率"]
        g["平均收益"] = g["平均收益"] * 100
        g["胜率"] = g["胜率"] * 100
        out[name] = g.round(2)
    return out


def session_stats(f: pd.DataFrame, horizon: int = 12) -> pd.DataFrame:
    d = f[["time", "close"]].copy()
    d["ret"] = d["close"].shift(-horizon) / d["close"] - 1.0
    h = d["time"].dt.hour
    sess = pd.case_when([
        (h < 7, "Asia (Tokyo/Sydney)"), (h < 12, "Europe early (pre-London)"),
        (h < 17, "EU-US overlap (main session)"), (h < 21, "Americas afternoon"),
    ]) if hasattr(pd, "case_when") else np.select(
        [h < 7, h < 12, h < 17, h < 21], ["Asia (Tokyo/Sydney)", "Europe early (pre-London)", "EU-US overlap (main session)", "Americas afternoon"],
        default="Americas late")
    d["sess"] = sess
    g = d.groupby("sess")["ret"].agg(["mean", "std", "count"])
    g["胜率"] = d.assign(w=d["ret"] > 0).groupby("sess")["w"].mean() * 100
    g.columns = ["平均收益", "波动", "样本数", "胜率"]
    g["平均收益"] *= 100
    return g.round(2)


def convergence_stats(f: pd.DataFrame, horizon: int = 24) -> pd.DataFrame:
    """Bollinger bandwidth percentile -> subsequent returns (validates the "enter at squeeze end" basis)."""
    d = pd.DataFrame({
        "w": f["bb_width"],
        "ret_up": f["close"].shift(-horizon) / f["close"] - 1.0,
        "ret_dn": f["close"].shift(-horizon) / f["close"] - 1.0,
    })
    q = d["w"].rank(pct=True)
    bucket = pd.cut(q, [0, .1, .25, .5, .75, .9, 1.0],
                    labels=["narrowest 10%", "10-25%", "25-50%", "50-75%", "75-90%", "widest 10%"])
    g = d.groupby(bucket, observed=True).agg(
        样本数=("ret_up", "size"),
        后续平均涨幅=("ret_up", "mean"),
        后续绝对波动=("ret_dn", lambda s: s.abs().mean()),
    )
    g["后续平均涨幅"] *= 100
    g["后续绝对波动"] *= 100
    g.index.name = "布林带带宽分位"
    return g.round(3)


def condition_attribution(f: pd.DataFrame, sig: pd.DataFrame, horizon: int = 24) -> pd.DataFrame:
    """Single-factor attribution for the five conditions: expected return / win rate over the next `horizon`
bars when the condition is met."""
    fut = f["close"].shift(-horizon) / f["close"] - 1.0
    rows = []
    conds = {
        "①回档(顾比)": sig["c1_pullback"].to_numpy() != 0,
        "②收口·乖离(布林)": sig["c2_band"].to_numpy() != 0,
        "③过度(随机)": sig["c3_over"].to_numpy() != 0,
        "④适离(斐波/轴心)": sig["c4_level"].to_numpy() != 0,
        "⑤渐短(蜡烛)": sig["c5_shrink"].to_numpy() != 0,
    }
    base_w = float((fut > 0).mean())
    base_m = float(fut.mean())
    for name, mask in conds.items():
        m = pd.Series(mask, index=f.index).fillna(False)
        if m.sum() < 10:
            continue
        rows.append({
            "要件": name, "出现次数": int(m.sum()),
            "出现占比%": round(float(m.mean()) * 100, 1),
            "后续平均收益%": round(float(fut[m].mean()) * 100, 3),
            "基准收益%": round(base_m * 100, 3),
            "后续胜率%": round(float((fut[m] > 0).mean()) * 100, 1),
            "基准胜率%": round(base_w * 100, 1),
        })
    return pd.DataFrame(rows)


def signal_forward_stats(f: pd.DataFrame, sig: pd.DataFrame, horizons=(6, 24, 72)) -> pd.DataFrame:
    """Forward performance after an entry signal appears (long / short separated)."""
    rows = []
    for h in horizons:
        fut = f["close"].shift(-h) / f["close"] - 1.0
        for side, col in ((1, "sig_long"), (-1, "sig_short")):
            m = sig[col].fillna(False).to_numpy()
            if m.sum() < 5:
                continue
            r = fut.to_numpy()[m] * side
            valid = ~np.isnan(r)
            if valid.sum() < 5:
                continue
            rows.append({"持仓根数": h, "方向": "long" if side > 0 else "short",
                         "信号数": int(m.sum()),
                         "平均收益%": round(float(np.nanmean(r)) * 100, 3),
                         "胜率%": round(float((r[valid] > 0).mean()) * 100, 1),
                         "中位收益%": round(float(np.nanmedian(r)) * 100, 3)})
    return pd.DataFrame(rows)
