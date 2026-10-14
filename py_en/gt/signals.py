"""Signal synthesis: assemble indicators into entry/exit signals covering trend, level, and microstructure.

1H chart (five conditions) - pullback (trend) / squeeze-divergence (meso state) / exhaustion /
                             proximity (level) / shrink (micro state)
4H chart (three patterns)  - bull/bear engulfing - morning/evening star - piercing/dark cloud cover,
                             and they must appear on the Bollinger band rail
Exit - close breaks the outer band after a large move; close re-crosses the mid band after a small move;
       trailing stop; close on a reverse entry signal
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from . import indicators as ind
from . import data as D


# --------------------------------------------------------------------------
def prepare(h1: pd.DataFrame, h4: Optional[pd.DataFrame] = None,
            d1: Optional[pd.DataFrame] = None, cfg: Optional[Dict] = None) -> pd.DataFrame:
    """Assemble all indicators/patterns onto the H1 master table."""
    cfg = cfg or {}
    h1 = h1.reset_index(drop=True).copy()
    f = h1.copy()

    # ATR
    f["atr"] = ind.atr(f, cfg.get("exit", {}).get("atr_period", 14))

    # Bollinger Bands (13, 0, 1.618)
    b = cfg.get("bollinger", {})
    bb = ind.bollinger(f, b.get("period", 13), b.get("deviation", 1.618))
    sq = ind.bb_squeeze(bb, b.get("squeeze_lookback", 120),
                        b.get("squeeze_percentile", 0.25), b.get("expand_bars", 2))
    f = pd.concat([f, bb, sq], axis=1)

    # Guppy multiple moving averages
    g = cfg.get("guppy", {})
    gg = ind.guppy(f, g.get("short", [3, 5, 8, 10, 12, 15]),
                   g.get("long", [30, 35, 40, 45, 50, 60]))
    pb = ind.guppy_pullback(gg, f["atr"], g.get("pullback_atr_ratio", 0.60))
    f = pd.concat([f, gg, pb], axis=1)

    # Stochastic oscillator
    s = cfg.get("stochastic", {})
    f = pd.concat([f, ind.stochastic(f, s.get("k_period", 5), s.get("d_period", 3),
                                     s.get("slowing", 3))], axis=1)

    # Candlestick features
    c = cfg.get("candle", {})
    f = pd.concat([f, ind.candle_features(f, c.get("body_lookback", 20),
                                          c.get("small_body_ratio", 0.60),
                                          c.get("shadow_multiple", 1.5),
                                          c.get("doji_body_range_ratio", 0.10))], axis=1)

    # Swings / Fibonacci / pivot points
    fb = cfg.get("fibonacci", {})
    left, right = fb.get("swing_left", 5), fb.get("swing_right", 5)
    sh, sl = ind.swing_points(f, left, right)
    f["swing_high"], f["swing_low"] = sh, sl
    leg = ind.fib_legs(f, sh, sl, right)
    piv = None
    if d1 is not None and cfg.get("pivot", {}).get("enabled", True):
        piv = ind.pivot_levels_daily(d1, cfg.get("pivot", {}).get("method", "classic"))
    lv = ind.nearest_levels(f, leg, piv, fb.get("retracements", [0, .236, .382, .5, .618, .786, 1]),
                            fb.get("extensions", [1.272, 1.618, 2.618]), out_cols=3)
    f = pd.concat([f, leg, lv], axis=1)
    f["n_dir"] = ind.n_pattern(sh, sl, right).to_numpy()

    # Align the 4H three-pattern signals onto H1
    if h4 is not None and cfg.get("h4", {}).get("enabled", True):
        f = _align_h4(f, h4, cfg)

    # Daily trend (the larger timeframe sets "trend"): use the previous completed trading day's value to avoid look-ahead
    if d1 is not None:
        f["d1_trend"] = _align_d1_trend(f, d1, cfg.get("entry", {}).get("trend_ema", 50))
    return f


def _align_d1_trend(f: pd.DataFrame, d1: pd.DataFrame, span: int,
                    clear_atr_mult: float = 0.6) -> pd.Series:
    """D1 trend in three states: clear up (+1) / clear down (-1) / unclear (0). Mapped onto H1.

Judgment (requires "clarity"; an ATR bandwidth threshold prevents misreading choppy markets):
  close deviates from EMA(span) by more than clear_atr_mult * ATR_D1, and the EMA slope agrees
  => clear trend; otherwise => 0 (no clear trend, regime takes the two-sided skew branch).
Use the prior completed trading day's value to avoid look-ahead.
"""
    d = d1.sort_values("time").reset_index(drop=True)
    close = d["close"].to_numpy()
    ema = d["close"].ewm(span=int(span), adjust=False).mean().to_numpy()
    atr = ind.atr(d, 14).to_numpy()
    atr = np.where(np.isfinite(atr), atr, 0.0)
    slope = np.zeros(len(ema))
    slope[1:] = ema[1:] - ema[:-1]
    dev = close - ema
    clear = np.abs(dev) > clear_atr_mult * atr
    up = clear & (dev > 0) & (slope > 0)
    dn = clear & (dev < 0) & (slope < 0)
    tv = np.where(up, 1, np.where(dn, -1, 0)).astype(float)
    dt = d["time"].to_numpy().astype("datetime64[ms]")
    ht = f["time"].to_numpy().astype("datetime64[ms]")
    pos = np.searchsorted(dt, ht, side="right") - 1
    pos = np.clip(pos - 1, 0, len(tv) - 1)  # -1: use only the prior day that has already closed
    return pd.Series(tv[pos], index=f.index, dtype=float)


def regime_decision(bias: int, d1_trend: int, skew: float = 0.4,
                    neutral_long_only: bool = True,
                    neutral_flat_aside: bool = False):
    """Fundamental bias x daily trend -> directional gating + position skew (relative to base position size).

Returns (allow_long, allow_short, long_skew, short_skew).
bias>0 bullish / bias<0 bearish / 0 neutral; d1_trend +1 clear up / -1 clear down / 0 unclear.

User framework:
  bearish + clear down  -> short only;          bearish + no clear down  -> two-sided (short>long)
  bullish + clear up    -> long only;           bullish + no clear up    -> two-sided (long>short)
  neutral               -> long-only (default) / two-sided equal / neutral-flat stands aside (B3).
Backtest evidence:
  - Under neutral bias, two-sided equal weighting opens "neutral shorts", and neutral shorts have
    PF ~= 0.6~0.8 (persistent losses), so neutral defaults back to the proven "long-only" edge
    (neutral_long_only=True). Setting it False restores the original "two-sided equal" for comparison.
  - Further: under neutral + no clear daily trend (=0), full-size long ("neutral-flat" bucket) is the
    biggest drag (PF 0.63, net loss ~ -14k), while neutral + daily already up/down still yields long PF
    1.4~1.7. Hence B3 is adopted: when neutral_flat_aside=True, neutral + no clear daily trend -> stand
    aside (no entries); only neutral but daily already up/down takes long.
"""
    b = 1 if bias > 0 else (-1 if bias < 0 else 0)
    t = 1 if d1_trend > 0 else (-1 if d1_trend < 0 else 0)
    if b < 0:                       # bearish bias
        if t == -1:                 # bearish + clear downtrend -> short only
            return (False, True, 0.0, 1.0)
        return (True, True, skew, 1.0)        # bearish + no clear trend -> both, short>long
    if b > 0:                       # bullish bias
        if t == 1:                   # bullish + clear uptrend -> long only
            return (True, False, 1.0, 0.0)
        return (True, True, 1.0, skew)         # bullish + no clear trend -> both, long>short
    # neutral: no fundamental directional view
    if t == 0 and neutral_flat_aside:
        return (False, False, 0.0, 0.0)   # neutral + no clear daily trend -> stand aside (B3)
    if neutral_long_only:
        return (True, False, 1.0, 0.0)  # fall back to proven long edge; no shorts
    return (True, True, 1.0, 1.0)        # equal both directions (control baseline)


def _align_h4(f: pd.DataFrame, h4: pd.DataFrame, cfg: Dict) -> pd.DataFrame:
    b = cfg.get("bollinger", {})
    x = h4.reset_index(drop=True).copy()
    x["h4_atr"] = ind.atr(x, cfg.get("exit", {}).get("atr_period", 14))
    bb = ind.bollinger(x, b.get("period", 13), b.get("deviation", 1.618))
    pat = ind.patterns(x, cfg.get("h4", {}).get("engulfing_body_ratio", 1.0))
    x = pd.concat([x, bb.add_prefix("h4_"), pat.add_prefix("h4_")], axis=1)
    tol = cfg.get("h4", {}).get("band_touch_atr", 0.50) * x["h4_atr"]
    x["h4_near_up"] = (x["h4_bb_up"] - x["close"]).abs() <= tol
    x["h4_near_lo"] = (x["close"] - x["h4_bb_lo"]).abs() <= tol
    x["h4_sig_long"] = x["h4_rev_bull"] & x["h4_near_lo"]
    x["h4_sig_short"] = x["h4_rev_bear"] & x["h4_near_up"]
    # Note: astype must come after the addition -- pandas 3.x Timedelta arithmetic upcasts ms precision to us
    x["h4_avail"] = (pd.to_datetime(x["time"]) + pd.Timedelta(hours=4)).astype(D.DT)
    cols = ["h4_avail", "h4_sig_long", "h4_sig_short", "h4_bb_mid", "h4_bb_up",
            "h4_bb_lo", "h4_rev_bull", "h4_rev_bear"]
    right = x[cols].sort_values("h4_avail")
    # Both keys must be ms (pandas 3.x datetime arithmetic upcasts to us, merge_asof would raise MergeError directly)
    left = f.sort_values("time").copy()
    left["time"] = pd.to_datetime(left["time"]).astype(D.DT)
    out = pd.merge_asof(left, right, left_on="time",
                        right_on="h4_avail", direction="backward")
    return out.sort_values("time").reset_index(drop=True).drop(columns=["h4_avail"])


# --------------------------------------------------------------------------
def entry_scores(f: pd.DataFrame, cfg: Dict) -> pd.DataFrame:
    """Five-condition scoring + final entry signal."""
    e = cfg.get("entry", {})
    s = cfg.get("stochastic", {})
    prox = cfg.get("level_proximity_atr", 0.35) * f["atr"]

    # ① Pullback (trend) -- must hold first
    pb_long = (f["g_state"] == 1) & f["pb_bull"]
    pb_short = (f["g_state"] == -1) & f["pb_bear"]

    # ② Squeeze [divergence] (medium-term convergence/divergence node)
    sq_ok = (f["bb_squeeze"] | f["bb_expand"]).fillna(False)
    diverge_long = f["close"] <= f["bb_lo"] + prox      # Lower band divergence -> long
    diverge_short = f["close"] >= f["bb_up"] - prox     # Upper band divergence -> short
    band_long = sq_ok | diverge_long
    band_short = sq_ok | diverge_short

    # ③ Exhaustion: rebound after oversold / pullback after overbought
    k = f["stoch_k"]
    os_recent = (k <= s.get("oversold", 20)).rolling(3, min_periods=1).max().astype(bool)
    ob_recent = (k >= s.get("overbought", 80)).rolling(3, min_periods=1).max().astype(bool)
    over_long = os_recent & (k > k.shift(1))
    over_short = ob_recent & (k < k.shift(1))

    # ④ Proximity (level): near key Fibonacci/pivot levels
    near_long = (f["lvd0"] <= prox) | (f["lvd1"] <= prox)
    near_short = near_long  # Levels are symmetric; direction is decided by trend

    # ⑤ Shrink (micro convergence/divergence)
    shrink = (f["convergence"] | f["flip_shrink"]).astype(bool)
    shrink = (shrink | shrink.shift(1, fill_value=False)).fillna(False).astype(bool)

    score_long = (pb_long.astype(int) + band_long.astype(int) + over_long.astype(int)
                  + near_long.astype(int) + shrink.astype(int))
    score_short = (pb_short.astype(int) + band_short.astype(int) + over_short.astype(int)
                   + near_short.astype(int) + shrink.astype(int))

    min_score = int(e.get("min_score", 5))
    sig_long = (score_long >= min_score)
    sig_short = (score_short >= min_score)
    if e.get("require_pullback", True):
        sig_long &= pb_long
        sig_short &= pb_short
    # Larger timeframe sets "trend": only take trades aligned with the daily trend
    if e.get("trend_filter", False) and "d1_trend" in f.columns:
        t = f["d1_trend"].fillna(0)
        sig_long &= (t > 0)
        sig_short &= (t < 0)
    if not e.get("allow_long", True):
        sig_long = pd.Series(False, index=f.index)
    if not e.get("allow_short", True):
        sig_short = pd.Series(False, index=f.index)

    # 4H three-pattern confluence (core of the original "Dina system"):
    #   Enter only when 1H five conditions AND 4H three patterns agree in direction (AND).
    #   h4_sig_long/short are computed by prepare()'s _align_h4 and aligned to H1.
    if e.get("require_h4_resonance", False) and "h4_sig_long" in f.columns:
        h4l = f["h4_sig_long"].fillna(False).astype(bool)
        h4s = f["h4_sig_short"].fillna(False).astype(bool)
        sig_long &= h4l
        sig_short &= h4s

    out = pd.DataFrame({
        "c1_pullback": np.where(pb_long, 1, np.where(pb_short, -1, 0)),
        "c2_band": np.where(band_long, 1, np.where(band_short, -1, 0)),
        "c3_over": np.where(over_long, 1, np.where(over_short, -1, 0)),
        "c4_level": near_long.astype(int),
        "c5_shrink": shrink.astype(int),
        "score_long": score_long, "score_short": score_short,
        "sig_long": sig_long, "sig_short": sig_short,
    }, index=f.index)
    return out


def initial_stop(f: pd.DataFrame, i: int, side: int, cfg: Dict) -> float:
    """Initial stop: beyond a valid key level + ATR buffer."""
    ex = cfg.get("exit", {})
    a = float(f["atr"].iloc[i])
    entry = float(f["close"].iloc[i])
    buf = ex.get("stop_buffer_atr", 0.30) * a
    cands = []
    for col in ("lv0", "lv1", "lv2", "bb_lo", "bb_up", "g_lmin", "g_lmax"):
        if col in f.columns:
            v = f[col].iloc[i]
            if np.isfinite(v):
                cands.append(float(v))
    if side > 0:
        below = [v for v in cands if v < entry]
        ref = max(below) if below else entry - ex.get("initial_stop_atr", 1.2) * a
        stop = ref - buf
        dist = entry - stop
    else:
        above = [v for v in cands if v > entry]
        ref = min(above) if above else entry + ex.get("initial_stop_atr", 1.2) * a
        stop = ref + buf
        dist = stop - entry
    min_d = ex.get("initial_stop_min_atr", 0.8) * a
    if dist < min_d:
        stop = entry - side * min_d
    return float(stop)
