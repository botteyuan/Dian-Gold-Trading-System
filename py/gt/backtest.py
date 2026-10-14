"""Backtest engine: strictly executes Dina's "five entry conditions + Bollinger exit + trailing stop".

Entry: after the confirmation signal bar closes, fill at the next bar's open (per the book's
"trade signal" definition).
Exit:
  1) Initial stop (beyond key level + ATR buffer)
  2) Large move then close breaks the outer Bollinger band -> close
  3) No large move then close re-crosses the middle band -> close
  4) Trailing stop (mid band / ATR)
  5) Reverse entry signal appears -> close
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import signals as SG


@dataclass
class Trade:
    side: int
    entry_time: pd.Timestamp
    entry: float
    stop0: float
    exit_time: Optional[pd.Timestamp] = None
    exit: float = 0.0
    stop: float = 0.0
    frac: float = 1.0
    realized: float = 0.0
    lots: float = 0.0
    pnl: float = 0.0
    r: float = 0.0
    reason: str = ""
    score: int = 0
    mfe: float = 0.0
    mae: float = 0.0
    entry_bar: int = 0
    regime_tag: str = ""      # status tag in regime mode (e.g. "long|short-bias down")


def _regime_tag(bias: int, d1: int, side: int) -> str:
    """Regime state label, for splitting performance by state."""
    b = "多偏" if bias > 0 else ("空偏" if bias < 0 else "中性")
    t = "涨" if d1 > 0 else ("跌" if d1 < 0 else "平")
    return f"{'多' if side > 0 else '空'}|{b}{t}"


@dataclass
class Result:
    trades: List[Trade] = field(default_factory=list)
    equity: pd.Series = None
    metrics: Dict = field(default_factory=dict)


def run(f: pd.DataFrame, cfg: Dict, sig: Optional[pd.DataFrame] = None,
        bias: int = 0, size_mult: float = 1.0, veto: bool = True,
        kelly: Optional[float] = None, initial_capital: float = 100000.0,
        use_regime: bool = False, bias_series=None, skew: float = 0.4,
        neutral_long_only: bool = True, neutral_flat_aside: bool = False,
        fixed_lot: Optional[float] = None,
        fixed_risk_pct: Optional[float] = None) -> Result:
    ex = cfg.get("exit", {})
    rk = cfg.get("risk", {})
    bt = cfg.get("backtest", {})
    pv = float(bt.get("point_value", 100))
    spread = float(bt.get("spread_points", 30)) * 0.01

    if sig is None:
        sig = SG.entry_scores(f, cfg)
    f = f.reset_index(drop=True)
    sig = sig.reset_index(drop=True)

    open_, high, low, close, time = (f[c].to_numpy() for c in ("open", "high", "low", "close", "time"))
    bbm, bbu, bbl = (f[c].to_numpy(float) for c in ("bb_mid", "bb_up", "bb_lo"))
    atr = f["atr"].to_numpy(float)
    sig_l = sig["sig_long"].to_numpy(bool)
    sig_s = sig["sig_short"].to_numpy(bool)
    score_l = sig["score_long"].to_numpy()
    score_s = sig["score_short"].to_numpy()

    # regime mode: align the bias series to the H1 index (ffill the daily-indexed Series),
    # so each H1 bar can pick up the fundamental bias of "its trading day".
    bs = None
    if use_regime:
        if "d1_trend" not in f.columns:
            raise ValueError("use_regime=True 需要 f 含 'd1_trend' 列（SG.prepare 时传入 d1）")
        if isinstance(bias_series, pd.Series):
            bs = bias_series.reindex(f["time"], method="ffill").fillna(0).astype(int).to_numpy()
        elif bias_series is None:
            bs = np.full(len(f), int(bias), dtype=int)
        else:
            bs = np.asarray(bias_series, dtype=int)
            if len(bs) != len(f):
                raise ValueError("bias_series 长度必须与 f 一致，或为按日索引的 Series")

    equity = initial_capital
    eq_curve = []
    trades: List[Trade] = []
    cur: Optional[Trade] = None
    peak = equity
    max_dd = 0.0

    def lots_for(entry: float, stop: float, sm: float = 1.0) -> float:
        if fixed_lot is not None:
            # Fixed-lot mode: a constant base lot, still scaled by the regime's
            # long/short skew (long=longSkew, short=shortSkew). The fundamental
            # size multiplier is NOT applied, so the lot stays literal.
            skew_factor = (sm / size_mult) if size_mult > 0 else sm
            return float(np.clip(fixed_lot * skew_factor,
                                 rk.get("min_lots", 0.01), rk.get("max_lots", 5.0)))
        dist = abs(entry - stop) * pv
        if dist <= 0:
            return rk.get("min_lots", 0.01)
        if fixed_risk_pct is not None:
            # ATR-equalized fixed-risk mode: every trade risks exactly
            # `fixed_risk_pct` % of equity, with the lot derived from the stop's
            # ATR distance. Kelly and the fundamental size multiplier are NOT
            # applied; only the regime long/short skew (longSkew/shortSkew) is
            # kept, so leverage stays volatility-adaptive but conviction-neutral.
            skew_factor = (sm / size_mult) if size_mult > 0 else sm
            amt = equity * fixed_risk_pct / 100.0 * skew_factor
            l = amt / dist
            return float(np.clip(l, rk.get("min_lots", 0.01), rk.get("max_lots", 5.0)))
        risk_pct = rk.get("account_risk_pct", 1.0)
        if kelly is not None and kelly > 0:
            # Kelly: f* is used directly as the per-trade risk exposure as a fraction of equity
            risk_pct = min(kelly * 100.0, rk.get("account_risk_pct", 1.0) * 3)
        amt = equity * risk_pct / 100.0 * size_mult * sm
        l = amt / dist
        return float(np.clip(l, rk.get("min_lots", 0.01), rk.get("max_lots", 5.0)))

    for i in range(1, len(f) - 1):
        px_open, px_close = open_[i], close[i]
        if cur is None:
            # Prior bar (i-1) gave the confirmation signal -> fill at this bar's open
            side = 0
            sm = size_mult
            rtag = ""
            if use_regime:
                b = int(bs[i - 1])
                dtv = f["d1_trend"].iloc[i - 1]
                dt = int(dtv) if np.isfinite(dtv) else 0
                al, ash, lsk, ssk = SG.regime_decision(b, dt, skew, neutral_long_only, neutral_flat_aside)
                if sig_l[i - 1] and al:
                    side, sm, rtag = 1, size_mult * lsk, _regime_tag(b, dt, 1)
                elif sig_s[i - 1] and ash:
                    side, sm, rtag = -1, size_mult * ssk, _regime_tag(b, dt, -1)
            else:
                if sig_l[i - 1] and not (veto and bias < 0):
                    side = 1
                elif sig_s[i - 1] and not (veto and bias > 0):
                    side = -1
            if side == 0:
                eq_curve.append((time[i], equity))
                continue
            stop = SG.initial_stop(f, i - 1, side, cfg)
            entry = px_open + (spread if side > 0 else 0.0)
            lots = lots_for(entry, stop, sm)
            cur = Trade(side=side, entry_time=time[i], entry=entry, stop0=stop,
                        lots=lots, score=int(score_l[i - 1] if side > 0 else score_s[i - 1]),
                        entry_bar=i, regime_tag=rtag)
            cur.stop = stop
            continue

        # ---- Position management ----
        t = cur
        partial = float(ex.get("partial_frac", 0.5))
        a = atr[i - 1] if np.isfinite(atr[i - 1]) else atr[i]
        # MFE/MAE updated only from the "closed" prior bar.
        # Using the current bar's high/low means knowing the extremes before the bar closes -- look-ahead bias.
        h_prev, l_prev = high[i - 1], low[i - 1]
        t.mfe = max(t.mfe, (h_prev - t.entry) if t.side > 0 else (t.entry - l_prev))
        t.mae = max(t.mae, (t.entry - l_prev) if t.side > 0 else (h_prev - t.entry))
        big = t.mfe >= ex.get("big_move_atr", 2.0) * a

        # Trailing stop: the stop level must be set "before" the bar starts; only information up to the prior close may be used.
        # The old implementation used bbm[i]/high[i] (including the current bar), effectively filling at future prices -- systematically inflating profit.
        tr = ex.get("trailing", {})
        if tr.get("enabled", True) and t.mfe >= tr.get("activate_atr", 1.0) * a:
            if tr.get("method", "bollinger") == "bollinger" and np.isfinite(bbm[i - 1]):
                cand = bbm[i - 1]
                if t.side > 0:
                    t.stop = max(t.stop, cand)
                else:
                    t.stop = min(t.stop, cand) if t.stop > 0 else cand
            else:
                cand = (h_prev - tr.get("atr_multiple", 2.0) * a) if t.side > 0 else \
                       (l_prev + tr.get("atr_multiple", 2.0) * a)
                t.stop = max(t.stop, cand) if t.side > 0 else min(t.stop, cand)

        exit_px, reason = None, ""
        # 1) Stop loss: on a gap, fill at the open price (cannot use the stop price, which is a non-existent fill)
        if t.side > 0 and low[i] <= t.stop:
            exit_px, reason = min(px_open, t.stop), "止损"
        elif t.side < 0 and high[i] >= t.stop:
            exit_px, reason = max(px_open, t.stop), "止损"
        # 2/3) Bollinger band exit
        if exit_px is None and np.isfinite(bbm[i]):
            if big and ex.get("close_beyond_outer", True):
                if t.side > 0 and px_close >= bbu[i]:
                    exit_px, reason = px_close, "大幅运动收盘破外轨"
                elif t.side < 0 and px_close <= bbl[i]:
                    exit_px, reason = px_close, "大幅运动收盘破外轨"
            if exit_px is None and not big and ex.get("close_beyond_middle", True):
                if t.side > 0 and px_close < bbm[i]:
                    exit_px, reason = px_close, "小幅运动收盘反穿中轨"
                elif t.side < 0 and px_close > bbm[i]:
                    exit_px, reason = px_close, "小幅运动收盘反穿中轨"
        # 6) Time stop: close at the bar's close once max holding bars is exceeded, to avoid capital being tied up indefinitely
        mh = int(ex.get("max_hold_bars", 0) or 0)
        if exit_px is None and mh > 0 and (i - t.entry_bar) >= mh:
            exit_px, reason = px_close, "时间止损"
        # 5) Reverse signal
        if exit_px is None and ex.get("reverse_signal_close", True):
            if (t.side > 0 and sig_s[i - 1]) or (t.side < 0 and sig_l[i - 1]):
                exit_px, reason = px_close, "反向进场信号"

        if exit_px is not None:
            px = exit_px - (spread if t.side < 0 else 0.0)
            # The "exit signal" in the book is essentially a partial-close signal: on first trigger, partial close and move the stop to cost,
            # leaving the remainder to the trailing stop (Dina's third law: cut loss, never take profit)
            if t.frac > 1.0 - 1e-9 and 0 < partial < 1.0:
                leg = t.lots * partial
                pnl = (px - t.entry) * t.side * leg * pv
                equity += pnl
                t.realized += pnl
                t.frac -= partial
                if ex.get("breakeven_after_partial", True):
                    be = t.entry + (0.10 * a if t.side > 0 else -0.10 * a)
                    t.stop = max(t.stop, be) if t.side > 0 else min(t.stop, be)
                cur = t
            else:
                leg = t.lots * t.frac
                pnl = (px - t.entry) * t.side * leg * pv + t.realized
                equity += pnl
                t.exit_time, t.exit, t.pnl, t.reason = time[i], px, pnl, reason
                t.r = (pnl / (abs(t.entry - t.stop0) * t.lots * pv)) if abs(t.entry - t.stop0) > 0 else 0.0
                trades.append(t)
                cur = None

        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        eq_curve.append((time[i], equity))

    if cur is not None:  # Force-close at the end
        px = close[-1]
        pnl = (px - cur.entry) * cur.side * cur.lots * cur.frac * pv + cur.realized
        equity += pnl
        cur.exit_time, cur.exit, cur.pnl, cur.reason = time[-1], px, pnl, "回测结束"
        trades.append(cur)

    eq = pd.Series([e for _, e in eq_curve], index=[t for t, _ in eq_curve], name="equity")
    return Result(trades=trades, equity=eq, metrics=metrics(trades, eq, initial_capital, max_dd))


def metrics(trades: List[Trade], eq: pd.Series, init: float, max_dd: float) -> Dict:
    if not trades:
        return {"交易次数": 0}
    pnl = np.array([t.pnl for t in trades])
    r = np.array([t.r for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    win_rate = len(wins) / len(pnl)
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = abs(losses.mean()) if len(losses) else 0.0
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else np.inf
    payoff = avg_win / avg_loss if avg_loss > 0 else np.inf
    expectancy = pnl.mean()
    ret = eq.iloc[-1] / init - 1
    days = max((eq.index[-1] - eq.index[0]).days, 1)
    cagr = (eq.iloc[-1] / init) ** (365.0 / days) - 1 if eq.iloc[-1] > 0 else -1
    daily = eq.resample("D").last().ffill().pct_change().dropna()
    sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    kelly_f = (win_rate * (payoff + 1) - 1) / payoff if np.isfinite(payoff) and payoff > 0 else 0.0
    return {
        "交易次数": len(trades),
        "胜率": round(win_rate * 100, 2),
        "平均盈利": round(float(avg_win), 2),
        "平均亏损": round(float(avg_loss), 2),
        "风险报酬率(盈亏比)": round(float(payoff), 2),
        "盈利因子": round(float(pf), 2),
        "单笔期望(元)": round(float(expectancy), 2),
        "平均R倍数": round(float(r.mean()), 3),
        "总收益率": round(ret * 100, 2),
        "年化(CAGR)": round(cagr * 100, 2),
        "最大回撤": round(max_dd * 100, 2),
        "夏普": round(float(sharpe), 2),
        "周转率(次/年)": round(len(trades) / (days / 365.0), 1),
        "凯利建议f*": round(float(kelly_f), 3),
    }


def trades_df(trades: List[Trade]) -> pd.DataFrame:
    return pd.DataFrame([{
        "方向": "多" if t.side > 0 else "空",
        "开仓时间": t.entry_time, "开仓价": round(t.entry, 2),
        "初始止损": round(t.stop0, 2), "手数": round(t.lots, 2),
        "平仓时间": t.exit_time, "平仓价": round(t.exit, 2),
        "盈亏": round(t.pnl, 2), "R": round(t.r, 2),
        "MFE": round(t.mfe, 2), "MAE": round(t.mae, 2),
        "要件分": t.score, "原因": t.reason, "regime": t.regime_tag,
    } for t in trades])
