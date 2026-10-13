"""All technical indicators / pattern recognition for the Dina system.

Implemented strictly per the book's definitions:
  Bands(13, 0, 1.618)        Bollinger Bands   - meso convergence/divergence / deviation / exit
  Guppy composite MAs (6+6)  - cross (alert) / pullback (confirmation) = trend
  Pivot points w/ blended Fibonacci - proximity = level
  Stochastic oscillator      - exhaustion
  Candle convergence / reversal patterns - shrink = microstructure
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Basics
# --------------------------------------------------------------------------


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"],
                      (df["high"] - pc).abs(),
                      (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1.0 / period, adjust=False).mean()


# --------------------------------------------------------------------------
# Bollinger Bands (13, 0, 1.618)
# --------------------------------------------------------------------------
def bollinger(df: pd.DataFrame, period: int = 13, dev: float = 1.618) -> pd.DataFrame:
    mid = df["close"].rolling(period, min_periods=period).mean()
    sd = df["close"].rolling(period, min_periods=period).std(ddof=0)
    up, lo = mid + dev * sd, mid - dev * sd
    width = (up - lo) / mid.replace(0, np.nan)
    return pd.DataFrame({"bb_mid": mid, "bb_up": up, "bb_lo": lo, "bb_width": width})


def bb_squeeze(bb: pd.DataFrame, lookback: int = 120, pct: float = 0.25,
               expand_bars: int = 2) -> pd.DataFrame:
    """Squeeze -> expansion (meso convergence/divergence node)."""
    w = bb["bb_width"]
    q = w.rolling(lookback, min_periods=max(20, lookback // 4)).quantile(pct)
    squeeze = (w <= q).fillna(False).astype(bool)
    expanding = (w > w.shift(1)).fillna(False).astype(bool)
    exp_cnt = expanding.rolling(expand_bars, min_periods=1).sum()
    return pd.DataFrame({"bb_squeeze": squeeze,
                         "bb_expand": ((exp_cnt >= expand_bars)
                                       & squeeze.shift(1, fill_value=False)).fillna(False).astype(bool)})


# --------------------------------------------------------------------------
# Guppy composite moving averages
# --------------------------------------------------------------------------
def guppy(df: pd.DataFrame, short: List[int], long: List[int]) -> pd.DataFrame:
    close = df["close"]
    sm = pd.DataFrame({f"s{p}": ema(close, p) for p in short})
    lm = pd.DataFrame({f"l{p}": ema(close, p) for p in long})
    s_min, s_max = sm.min(axis=1), sm.max(axis=1)
    l_min, l_max = lm.min(axis=1), lm.max(axis=1)
    # Golden-cross state: all short-term lines above all long-term lines; death cross is the opposite
    bull = (s_min > l_max)
    bear = (s_max < l_min)
    state = pd.Series(0, index=df.index, dtype=int)
    state[bull] = 1
    state[bear] = -1
    state = state.replace(0, np.nan).ffill().fillna(0).astype(int)
    # Distance (ATR normalization done externally)
    return pd.DataFrame({"g_smin": s_min, "g_smax": s_max,
                         "g_lmin": l_min, "g_lmax": l_max, "g_state": state})


def guppy_pullback(g: pd.DataFrame, atr_s: pd.Series, ratio: float = 0.60) -> pd.DataFrame:
    """Pullback = after a cross, the short group approaches but does not cross the long group."""
    st = g["g_state"]
    bull_gap = (g["g_smin"] - g["g_lmax"]) / atr_s
    bear_gap = (g["g_lmin"] - g["g_smax"]) / atr_s
    pb_bull = (st == 1) & (bull_gap > 0) & (bull_gap <= ratio)
    pb_bear = (st == -1) & (bear_gap > 0) & (bear_gap <= ratio)
    return pd.DataFrame({"g_bull_gap": bull_gap, "g_bear_gap": bear_gap,
                         "pb_bull": pb_bull, "pb_bear": pb_bear})


# --------------------------------------------------------------------------
# Stochastic oscillator
# --------------------------------------------------------------------------
def stochastic(df: pd.DataFrame, k: int = 5, d: int = 3, slowing: int = 3) -> pd.DataFrame:
    ll = df["low"].rolling(k, min_periods=k).min()
    hh = df["high"].rolling(k, min_periods=k).max()
    rng = (hh - ll).replace(0, np.nan)
    raw = (df["close"] - ll) / rng * 100.0
    kk = raw.rolling(slowing, min_periods=1).mean()
    dd = kk.rolling(d, min_periods=1).mean()
    return pd.DataFrame({"stoch_k": kk, "stoch_d": dd})


# --------------------------------------------------------------------------
# Swing points / pivot points with blended Fibonacci
# --------------------------------------------------------------------------
def swing_points(df: pd.DataFrame, left: int = 5, right: int = 5) -> Tuple[np.ndarray, np.ndarray]:
    """Fractal swing highs/lows (value appears on the pivot bar, confirmed after `right` bars)."""
    n = len(df)
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    sh = np.full(n, np.nan)
    sl = np.full(n, np.nan)
    for i in range(left, n - right):
        seg_h = h[i - left:i + right + 1]
        seg_l = l[i - left:i + right + 1]
        if h[i] == seg_h.max():
            sh[i] = h[i]
        if l[i] == seg_l.min():
            sl[i] = l[i]
    return sh, sl


def _pivot_events(sh: np.ndarray, sl: np.ndarray, right: int):
    ev = []
    for i in np.flatnonzero(~np.isnan(sh)):
        ev.append((int(i) + right, +1, float(sh[i])))
    for i in np.flatnonzero(~np.isnan(sl)):
        ev.append((int(i) + right, -1, float(sl[i])))
    ev.sort(key=lambda x: (x[0], x[1]))
    return ev


def fib_legs(df: pd.DataFrame, sh: np.ndarray, sl: np.ndarray, right: int) -> pd.DataFrame:
    """Per-bar current "impulse wave" high/low (used for Fibonacci retracement/extension)."""
    n = len(df)
    ev = _pivot_events(sh, sl, right)
    hi = np.full(n, np.nan)
    lo = np.full(n, np.nan)
    d = np.zeros(n, dtype=int)
    last_h = np.nan
    last_l = np.nan
    last_type = 0
    ptr = 0
    for t in range(n):
        while ptr < len(ev) and ev[ptr][0] <= t:
            _, typ, price = ev[ptr]
            if typ == 1:
                last_h = price
            else:
                last_l = price
            last_type = typ
            ptr += 1
        hi[t], lo[t] = last_h, last_l
        # Most recent pivot is a high -> up impulse wave; is a low -> down impulse wave
        d[t] = 1 if last_type == 1 else (-1 if last_type == -1 else 0)
    return pd.DataFrame({"leg_high": hi, "leg_low": lo, "leg_dir": d}, index=df.index)


def pivot_levels_daily(d1: pd.DataFrame, method: str = "classic") -> pd.DataFrame:
    """Classic pivot points: map levels computed from the prior day's HLC onto the current day."""
    H, L, C = d1["high"], d1["low"], d1["close"]
    P = (H + L + C) / 3.0
    out = pd.DataFrame({
        "P": P,
        "R1": 2 * P - L, "S1": 2 * P - H,
        "R2": P + (H - L), "S2": P - (H - L),
        "R3": H + 2 * (P - L), "S3": L - 2 * (P - H),
    })
    if method == "fibonacci":
        rng = H - L
        out = pd.DataFrame({
            "P": P,
            "R1": P + 0.382 * rng, "S1": P - 0.382 * rng,
            "R2": P + 0.618 * rng, "S2": P - 0.618 * rng,
            "R3": P + 1.000 * rng, "S3": P - 1.000 * rng,
        })
    out.index = pd.to_datetime(d1["time"]).dt.normalize()
    return out.shift(1)  # Use the prior day's pivot points for the current day


def nearest_levels(df: pd.DataFrame, leg: pd.DataFrame, piv: Optional[pd.DataFrame],
                   retr: List[float], ext: List[float], out_cols: int = 3) -> pd.DataFrame:
    """Per-bar: the N key levels closest to the current price (Fibonacci retracement + extension + pivot points)."""
    n = len(df)
    dts = pd.to_datetime(df["time"]).dt.normalize().to_numpy()
    piv_dts = piv.index.to_numpy() if piv is not None else np.array([])
    piv_mat = piv.to_numpy(float) if piv is not None else np.zeros((0, 6))

    hi = leg["leg_high"].to_numpy(float)
    lo = leg["leg_low"].to_numpy(float)
    dr = leg["leg_dir"].to_numpy(int)
    close = df["close"].to_numpy(float)

    near = np.full((n, out_cols), np.nan)
    dist = np.full((n, out_cols), np.nan)
    for t in range(n):
        if not np.isfinite(hi[t]) or not np.isfinite(lo[t]) or dr[t] == 0:
            cands: List[float] = []
        else:
            rng = hi[t] - lo[t]
            if rng <= 0:
                cands = []
            elif dr[t] == 1:  # up impulse wave: retrace down from the high
                cands = [hi[t] - rng * r for r in retr] + [hi[t] + rng * (e - 1) for e in ext]
            else:             # down impulse wave: rebound up from the low
                cands = [lo[t] + rng * r for r in retr] + [lo[t] - rng * (e - 1) for e in ext]
        if piv is not None and len(piv_dts):
            j = np.searchsorted(piv_dts, dts[t], side="right") - 1
            if j >= 0:
                cands = cands + [float(x) for x in piv_mat[j] if np.isfinite(x)]
        if not cands:
            continue
        arr = np.array(sorted(cands), dtype=float)
        dd = np.abs(arr - close[t])
        k = min(out_cols, len(arr))
        idx = np.argsort(dd)[:k]
        near[t, :k] = arr[idx]
        dist[t, :k] = dd[idx]
    return pd.DataFrame({f"lv{i}": near[:, i] for i in range(out_cols)} |
                        {f"lvd{i}": dist[:, i] for i in range(out_cols)}, index=df.index)


# --------------------------------------------------------------------------
# Candlestick convergence/divergence / patterns
# --------------------------------------------------------------------------
def candle_features(df: pd.DataFrame, lookback: int = 20, ratio: float = 0.60,
                    shadow_mult: float = 1.5, doji_ratio: float = 0.10) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    up_sh = h - np.maximum(o, c)
    dn_sh = np.minimum(o, c) - l
    shadow = up_sh + dn_sh
    avg_body = body.rolling(lookback, min_periods=max(5, lookback // 3)).mean()

    small_body = body <= ratio * avg_body
    doji = body / rng <= doji_ratio
    long_shadow = shadow >= shadow_mult * body.replace(0, np.nan).fillna(1e-9)
    # Convergent candle (alert signal): small body or doji
    convergence = (small_body | doji).fillna(False)
    # Shrinking shadow: this candle's shadow shorter than the prior one and body not enlarged
    shrinking = (shadow < shadow.shift(1)) & (body <= body.shift(1))
    return pd.DataFrame({
        "body": body, "range": rng, "shadow": shadow,
        "up_shadow": up_sh, "dn_shadow": dn_sh,
        "small_body": small_body.fillna(False),
        "doji": doji.fillna(False),
        "convergence": convergence,
        "flip_shrink": (shrinking & convergence).fillna(False),
        "bull": (c > o), "bear": (c < o),
    })


def _body(o, c):
    return (c - o).abs()


def patterns(df: pd.DataFrame, engulf_ratio: float = 1.0) -> pd.DataFrame:
    """4H chart three patterns: bullish/bearish engulfing / morning-evening star / piercing-dark cloud cover."""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    n = len(df)
    b = np.abs(c - o)
    bull, bear = c > o, c < o
    idx = df.index

    def sh(col, k):
        return pd.Series(np.r_[np.full(k, False), col], index=idx)

    # Engulfing
    eng_bull = np.zeros(n, bool)
    eng_bear = np.zeros(n, bool)
    for i in range(1, n):
        if bear[i - 1] and bull[i]:
            if c[i] >= o[i - 1] and o[i] <= c[i - 1] and b[i] >= engulf_ratio * b[i - 1]:
                eng_bull[i] = True
        if bull[i - 1] and bear[i]:
            if c[i] <= o[i - 1] and o[i] >= c[i - 1] and b[i] >= engulf_ratio * b[i - 1]:
                eng_bear[i] = True
    # Morning/Evening star (morning star / evening star)
    morn = np.zeros(n, bool)
    even = np.zeros(n, bool)
    avg = pd.Series(b).rolling(20, min_periods=5).mean().to_numpy()
    for i in range(2, n):
        small_mid = b[i - 1] <= 0.6 * avg[i - 1]
        if not small_mid:
            continue
        mid1 = (o[i - 2] + c[i - 2]) / 2
        mid0 = (o[i - 2] + c[i - 2]) / 2
        if bear[i - 2] and bull[i] and c[i] > mid1:
            morn[i] = True
        if bull[i - 2] and bear[i] and c[i] < mid0:
            even[i] = True
    # Piercing / dark cloud cover
    pierce = np.zeros(n, bool)
    dark = np.zeros(n, bool)
    for i in range(1, n):
        midp = (o[i - 1] + c[i - 1]) / 2
        if bear[i - 1] and bull[i] and o[i] < c[i - 1] and c[i] > midp and c[i] < o[i - 1]:
            pierce[i] = True
        if bull[i - 1] and bear[i] and o[i] > c[i - 1] and c[i] < midp and c[i] > o[i - 1]:
            dark[i] = True
    return pd.DataFrame({
        "engulf_bull": eng_bull, "engulf_bear": eng_bear,
        "morning_star": morn, "evening_star": even,
        "piercing": pierce, "dark_cloud": dark,
        "rev_bull": eng_bull | morn | pierce,
        "rev_bear": eng_bear | even | dark,
    }, index=idx)


# --------------------------------------------------------------------------
# N-pattern rule (trend: trend-direction confirmation)
# --------------------------------------------------------------------------
def n_pattern(sh: np.ndarray, sl: np.ndarray, right: int) -> pd.Series:
    """+1 rising N / -1 falling N / 0 undecided. Emitted per bar."""
    n = len(sh)
    ev = _pivot_events(sh, sl, right)
    out = np.zeros(n, dtype=int)
    seq: List[Tuple[int, float]] = []  # (type, price) confirmed
    ptr = 0
    cur = 0
    for t in range(n):
        while ptr < len(ev) and ev[ptr][0] <= t:
            _, typ, price = ev[ptr]
            if not seq or seq[-1][0] != typ:
                seq.append((typ, price))
            else:  # Same type updates to a more extreme value
                if (typ == 1 and price > seq[-1][1]) or (typ == -1 and price < seq[-1][1]):
                    seq[-1] = (typ, price)
            if len(seq) >= 4:
                a, b, cc = seq[-3], seq[-2], seq[-1]
                if a[0] == -1 and b[0] == 1 and cc[0] == -1:
                    cur = 1 if cc[1] > a[1] else 0     # rising N: pullback low above the start
                elif a[0] == 1 and b[0] == -1 and cc[0] == 1:
                    cur = -1 if cc[1] < a[1] else 0    # falling N: rebound high below the start
            ptr += 1
        out[t] = cur
    return pd.Series(out, index=range(n))
