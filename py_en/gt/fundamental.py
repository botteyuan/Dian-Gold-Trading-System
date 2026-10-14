"""Driver analysis (fundamentals) - the logical hierarchy of gold drivers.

Per the book:
  Monetary attribute: 1) Geo-politics  2) Economic growth
  Investment attribute: 1) Rate level  2) Capital flow
  Commodity attribute: 1) Jewelry demand  2) Industrial use
Plus a manually-entered "central-bank buying" item that cannot be auto-fetched.

Each factor is scored -2..+2 (positive = bullish for gold); weighted into a total -10..+10.
Fundamentals only set "bias / veto / size scaling"; the entry trigger is always the technical
trend-level-microstructure setup.
"""
from __future__ import annotations

import json
from typing import Dict, Optional

import numpy as np
import pandas as pd

from . import data as D
from . import goldorg as GO


def _z(s: Optional[pd.Series], window: int = 250) -> float:
    if s is None or len(s) < 40:
        return 0.0
    v = float(s.iloc[-1])
    hist = s.iloc[-(window + 1):-1].astype(float)
    mu, sd = float(hist.mean()), float(hist.std(ddof=0))
    if not np.isfinite(sd) or sd == 0:
        return 0.0
    return float(np.clip((v - mu) / sd, -2.0, 2.0))


def _momentum_z(s: Optional[pd.Series], lookback: int = 63, window: int = 250) -> float:
    if s is None or len(s) < lookback + 60:
        return 0.0
    mom = (s / s.shift(lookback) - 1.0).dropna()
    return _z(mom, window)


def _periods_per_year(s: Optional[pd.Series]) -> int:
    """Infer frequency from the median gap between adjacent index entries: monthly=12 / weekly=52 / daily=252.
FRED mixes daily (VIXCLS) and monthly (INDPRO), so the YoY window cannot be hard-coded."""
    if s is None or len(s) < 3:
        return 252
    try:
        gap = pd.Series(pd.to_datetime(s.index)).diff().dt.days.dropna().median()
    except Exception:
        return 252
    if not np.isfinite(gap) or gap <= 0:
        return 252
    if gap >= 25:
        return 12
    if gap >= 6:
        return 52
    return 252


def _yoy_z(s: Optional[pd.Series], window: Optional[int] = None) -> float:
    """Year-over-year z-score (12-period / 252-period, frequency-adaptive).
The old implementation hard-coded len<400 returning 0, which silently zeroed out the monthly
INDPRO (139 rows) - a silent failure."""
    if s is None:
        return 0.0
    ppy = _periods_per_year(s)
    if len(s) < ppy + 24:
        return 0.0
    w = window if window is not None else max(48, min(ppy * 5, 250))
    return _z(s.pct_change(ppy).dropna(), w)


def _stale(s: Optional[pd.Series], tol: int = 7) -> str:
    """Staleness marker: warn that data is not latest when falling back to cache."""
    d = D.stale_days(s)
    return "" if d is None or d <= tol else f"[data as of {d} days ago]"


_LAST_BIAS_FILE = "last_fundamental.json"


def _last_bias_path() -> str:
    from .config import project_root
    import os
    return os.path.join(project_root(), "data", "cache", _LAST_BIAS_FILE)


def _save_last_bias(rec: Dict) -> None:
    """Persist the current valid bias to disk, to reuse on disconnect / missing data (avoid silently going neutral)."""
    try:
        with open(_last_bias_path(), "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
    except Exception:
        pass


def _load_last_bias() -> Optional[Dict]:
    try:
        with open(_last_bias_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _rolling_z(s: Optional[pd.Series], window: int = 250) -> pd.Series:
    """Rolling z-score (uses only the past window up to the current day; no look-ahead)."""
    if s is None or len(s) < 40:
        return pd.Series(dtype=float)
    s = s.astype(float).sort_index()
    mu = s.rolling(window, min_periods=max(40, window // 2)).mean()
    sd = s.rolling(window, min_periods=max(40, window // 2)).std(ddof=0)
    return ((s - mu) / sd).clip(-2.0, 2.0)


def _rolling_yoy_z(s: Optional[pd.Series], ppy: int = 12) -> pd.Series:
    """Rolling year-over-year z-score (monthly ppy=12 / daily ppy=252)."""
    if s is None or len(s) < ppy + 24:
        return pd.Series(dtype=float)
    g = s.pct_change(ppy)
    return _rolling_z(g, min(250, len(s) // 2))


def historical_bias(dates_index: pd.DatetimeIndex, cfg: Dict,
                    use_network: bool = True) -> pd.Series:
    """Reconstruct a daily fundamental bias series (same basis as analyze, but using only price-independent
macro factors).

Factors used (price-independent, with FRED/CBOE history): geo-politics (VIX), growth (INDPRO),
rate level (DFII10 real yield). Jewelry / industrial / central-bank / ETF flows are quarterly manual
items, set to 0 in historical backtests (weights excluded), so historical bias is driven by the three
factors "rate + safe-haven + growth".

For each trading day: compute the z-score from the rolling window up to that day -> weight -> threshold
to a bias (-1/0/1). Naturally look-ahead free (window uses only the past). Returns an integer series
aligned (forward-filled) to dates_index.
"""
    fc = cfg.get("fundamental", {})
    w = dict(fc.get("weights", {}))
    src = cfg.get("data", {})
    fred = src.get("fred_series", {})

    parts: Dict[str, pd.Series] = {}
    if use_network:
        # ① Geo-politics: VIX z (consistent with analyze; _z default window 250, weight 0.7)
        try:
            vix = D.cboe_vix(start="2014-01-01")
        except Exception:
            vix = None
        if vix is not None and len(vix) > 40:
            parts["geopolitics"] = _rolling_z(vix, 250) * 0.7
        # ② Growth: INDPRO YoY, inverted
        try:
            indpro = D.fred_series(fred.get("industrial", "INDPRO"))
        except Exception:
            indpro = None
        if indpro is not None:
            parts["growth"] = -_rolling_yoy_z(indpro, 12)
        # ③ Rate level: DFII10 real yield (level z + 60d change z, same formula as analyze)
        try:
            dfii = D.fred_series(fred.get("real_rate", "DFII10"))
        except Exception:
            dfii = None
        if dfii is not None and len(dfii) > 60:
            lvl = -_rolling_z(dfii, 250)
            chg = -_rolling_z(dfii.diff(60).dropna(), 250) * 0.6
            rr = (lvl + chg.reindex(lvl.index).fillna(0.0)) / 1.6 * 1.2
            parts["real_rate"] = rr

    idx = pd.DatetimeIndex(dates_index)
    acc = pd.Series(0.0, index=idx)
    total_w = 0.0
    for k, ser in parts.items():
        wk = float(w.get(k, 0.0))
        if wk == 0 or ser is None or len(ser) == 0:
            continue
        s = ser.reindex(idx, method="ffill").fillna(0.0)
        acc = acc + s * wk
        total_w += wk
    if total_w == 0:
        total_w = 1.0
    norm = acc / total_w
    score = norm * 5.0
    thr = float(fc.get("bias_threshold", 2.0))
    bias = np.where(score >= thr, 1, np.where(score <= -thr, -1, 0))
    return pd.Series(bias, index=idx).astype(int)


def _gdt_yoy_score(gdt: Optional[Dict], key: str, scale: float = 30.0) -> Optional[float]:
    """WGC quarterly YoY% -> -2..+2. A YoY of scale% maps to +/-1; a sign flip maps to the extreme value.

For indicators like ETF flows, "net inflow turning to net outflow" makes percentages meaningless,
so directly record -2 / +2.
"""
    if not gdt:
        return None
    cur = gdt.get("latest", {}).get(key)
    base = gdt.get("year_ago", {}).get(key)
    if cur is None or base is None:
        return None
    if base > 0 and cur < 0:
        return -2.0
    if base < 0 and cur > 0:
        return 2.0
    if base == 0:
        return 0.0
    return float(np.clip((cur / abs(base) - 1.0) * 100.0 / scale, -2.0, 2.0))


def analyze(cfg: Dict, use_network: bool = True, lang: str = "zh") -> Dict:
    fc = cfg.get("fundamental", {})
    w = dict(fc.get("weights", {}))
    w.setdefault("central_bank", 1.5)
    man = fc.get("manual", {})
    src = cfg.get("data", {})

    parts: Dict[str, Dict[str, float]] = {}

    def put(name: str, score: float, note: str, note_en: Optional[str] = None, missing: bool = False):
        parts[name] = {"score": float(np.clip(score, -2.0, 2.0)), "weight": float(w.get(name, 0.0)),
                       "note": note, "note_en": note_en if note_en is not None else note,
                       "missing": missing}

    # World Gold Council "Gold Demand Trends" quarterly supply/demand table
    # If available, replace the proxies of 4 factors (central-bank buying / capital flow / jewelry / industrial) with measured tonnage
    gdt = None
    if use_network and fc.get("wgc_enabled", True):
        try:
            gdt = GO.fetch_gdt(timeout=fc.get("wgc_timeout", 20))
        except Exception:
            gdt = None
    gdt_tag = f"[WGC {gdt['quarter']}]" if gdt else ""

    if use_network:
        # ① Monetary attribute - Geo-politics: VIX (safe-haven sentiment proxy) + manual item
        #    Multi-source fallback: CBOE official CSV (most authoritative, original publisher) -> FRED VIXCLS -> yfinance.
        #    When migrating machines a source often fails due to firewall/rate-limiting; try sources in order to always obtain a set.
        vix, vix_src = None, ""
        for name, fn in (
            ("CBOE",     lambda: D.cboe_vix()),
            ("FRED",     lambda: D.fred_series(src.get("fred_series", {}).get("vix", "VIXCLS"))),
            ("yfinance", lambda: D.yf_close(src.get("yfinance_tickers", {}).get("vix", "^VIX"))),
        ):
            try:
                s = fn()
            except Exception:
                s = None
            if s is not None and len(s) > 30:
                vix, vix_src = s, name
                break
        geo_avail = vix is not None
        if vix is not None:
            put("geopolitics", _z(vix) * 0.7 + float(man.get("central_bank_buying", 0.0)) * 0.5,
                f"VIX={float(vix.iloc[-1]):.2f} (higher = more bullish for gold)  src={vix_src}{_stale(vix)}",
                note_en=f"VIX={float(vix.iloc[-1]):.2f} (higher = more bullish for gold)  src={vix_src}{_stale(vix)}",
                missing=not geo_avail)
        else:
            put("geopolitics", 0.0, "VIX data missing (CBOE/FRED/yfinance all failed)",
                note_en="VIX data missing (CBOE/FRED/yfinance all failed)", missing=True)

        # ② Monetary attribute - Growth: industrial production YoY (strong economy -> weaker monetary attribute of gold)
        indpro = D.fred_series(src.get("fred_series", {}).get("industrial", "INDPRO"))
        growth_avail = indpro is not None
        if indpro is not None:
            put("growth", -_yoy_z(indpro),
                "Industrial production YoY, inverted (weak economy = bullish gold)" + _stale(indpro),
                note_en="Industrial production YoY, inverted (weak economy = bullish gold)" + _stale(indpro),
                missing=not growth_avail)
        else:
            put("growth", 0.0, "INDPRO data missing",
                note_en="INDPRO data missing", missing=True)

        # ③ Investment attribute - Rate level: 10Y TIPS real yield (core inverted indicator)
        dfii = D.fred_series(src.get("fred_series", {}).get("real_rate", "DFII10"))
        real_avail = dfii is not None and len(dfii) > 60
        if real_avail:
            lvl = -_z(dfii)
            chg = -_z(dfii.diff(60).dropna()) * 0.6
            put("real_rate", (lvl + chg) / 1.6 * 1.2,
                f"10Y TIPS real yield={float(dfii.iloc[-1]):.2f}% (level & 60d change both inverted){_stale(dfii)}",
                note_en=f"10Y TIPS real yield={float(dfii.iloc[-1]):.2f}% (level & 60d change both inverted){_stale(dfii)}")
        else:
            put("real_rate", 0.0, "DFII10 data missing",
                note_en="DFII10 data missing", missing=True)

        # ④ Investment attribute - Capital flow: prefer WGC measured ETF flows in tonnes (GLD momentum often unavailable)
        s_etf = _gdt_yoy_score(gdt, "etf", fc.get("gdt_scale", {}).get("etf", 30.0))
        if s_etf is not None:
            put("capital_flow", s_etf,
                f"ETF flows {gdt['latest']['etf']:+.1f}t (vs {gdt['year_ago']['etf']:+.1f}t a year ago){gdt_tag}",
                note_en=f"ETF flows {gdt['latest']['etf']:+.1f}t (vs {gdt['year_ago']['etf']:+.1f}t a year ago){gdt_tag}")
        else:
            gld = D.yf_close(src.get("yfinance_tickers", {}).get("etf", "GLD"))
            if gld is not None:
                put("capital_flow", _momentum_z(gld),
                    f"SPDR gold ETF 3M momentum (fund-flow proxy){_stale(gld)}",
                    note_en=f"SPDR gold ETF 3M momentum (fund-flow proxy){_stale(gld)}")
            else:
                put("capital_flow", 0.0, "GLD data missing (WGC also unavailable)",
                    note_en="GLD data missing (WGC also unavailable)", missing=True)

        # ⑤ Commodity attribute - Jewelry demand: prefer WGC measured jewelry consumption in tonnes, else fall back to seasonal proxy
        s_jew = _gdt_yoy_score(gdt, "jewelry", fc.get("gdt_scale", {}).get("jewelry", 30.0))
        if s_jew is not None:
            put("jewelry", s_jew + float(man.get("jewelry_demand", 0.0)),
                f"Jewelry demand {gdt['latest']['jewelry']:.1f}t (YoY {gdt['yoy']['jewelry']:+.1f}%){gdt_tag}",
                note_en=f"Jewelry demand {gdt['latest']['jewelry']:.1f}t (YoY {gdt['yoy']['jewelry']:+.1f}%){gdt_tag}")
        else:
            month = pd.Timestamp.today().month
            season = {11: 0.8, 12: 1.0, 1: 1.0, 2: 0.5, 3: 0.2, 4: 0.0, 5: -0.2,
                      6: -0.4, 7: -0.3, 8: 0.0, 9: 0.3, 10: 0.6}.get(month, 0.0)
            put("jewelry", season + float(man.get("jewelry_demand", 0.0)),
                f"Jewelry seasonality (month={month}) + manual",
                note_en=f"Jewelry seasonality (month={month}) + manual")

        # ⑥ Commodity attribute - Industrial gold: prefer WGC measured tech-sector gold in tonnes, else fall back to industrial production YoY
        s_tech = _gdt_yoy_score(gdt, "technology", fc.get("gdt_scale", {}).get("technology", 30.0))
        if s_tech is not None:
            put("industrial", s_tech + float(man.get("industrial_demand", 0.0)),
                f"Tech-sector gold {gdt['latest']['technology']:.1f}t (YoY {gdt['yoy']['technology']:+.1f}%){gdt_tag}",
                note_en=f"Tech-sector gold {gdt['latest']['technology']:.1f}t (YoY {gdt['yoy']['technology']:+.1f}%){gdt_tag}")
        else:
            if indpro is not None:
                put("industrial", _yoy_z(indpro) * 0.5 + float(man.get("industrial_demand", 0.0)),
                    "Industrial gold tracks real economy", note_en="Industrial gold tracks real economy")
            else:
                put("industrial", 0.0, "INDPRO data missing",
                    note_en="INDPRO data missing", missing=True)

        # ⑦ Central-bank buying: prefer WGC measured tonnage (previously only manually entered)
        s_cb = _gdt_yoy_score(gdt, "central_bank", fc.get("gdt_scale", {}).get("central_bank", 30.0))
        if s_cb is not None:
            put("central_bank", s_cb + float(man.get("central_bank_buying", 0.0)) * 0.5,
                f"Central-bank buying {gdt['latest']['central_bank']:.1f}t (YoY {gdt['yoy']['central_bank']:+.1f}%){gdt_tag}",
                note_en=f"Central-bank buying {gdt['latest']['central_bank']:.1f}t (YoY {gdt['yoy']['central_bank']:+.1f}%){gdt_tag}")
        else:
            put("central_bank", float(man.get("central_bank_buying", 0.0)),
                "Central-bank buying (World Gold Council quarterly data, manual)",
                note_en="Central-bank buying (World Gold Council quarterly data, manual)")
    else:
        for k in ["geopolitics", "growth", "real_rate", "capital_flow", "jewelry",
                  "industrial", "central_bank"]:
            put(k, float(man.get(k, 0.0)) if k in man else 0.0,
                "Offline mode: manual inputs only", note_en="Offline mode: manual inputs only")

    total_w = sum(p["weight"] for p in parts.values()) or 1.0
    avail_w = float(sum(p["weight"] for k, p in parts.items() if not p.get("missing", False)))
    coverage = avail_w / total_w if total_w else 1.0

    raw = sum(p["score"] * p["weight"] for p in parts.values())
    norm = raw / total_w                       # range -2 .. +2
    score = norm * 5.0                         # range -10 .. +10
    thr = float(fc.get("bias_threshold", 2.0))

    # ---- Macro coverage and bias reliability ----
    # The three macro factors (geo-politics / growth / real rate) are the main drivers of bias. If the running machine cannot reach
    # FRED/CBOE and they go missing together, treating "missing" as "neutral" would silently make the EA stand aside and not trade,
    # which is more dangerous than an error. Hence at low coverage we carry over the last valid bias and flag it, rather than silently going neutral.
    bias_state = "ok"
    carried_from = ""
    data_note = ""
    macro_cov = 1.0
    if use_network:
        macro_keys = ["geopolitics", "growth", "real_rate"]
        macro_w_total = float(sum(w.get(k, 0.0) for k in macro_keys))
        macro_w_avail = float(sum(w.get(k, 0.0) for k in macro_keys
                                  if (k == "geopolitics" and geo_avail) or
                                     (k == "growth" and growth_avail) or
                                     (k == "real_rate" and real_avail)))
        macro_cov = (macro_w_avail / macro_w_total) if macro_w_total > 0 else 1.0

    if use_network and macro_cov < 0.5:
        rec = _load_last_bias()
        rec_ok = rec and (pd.Timestamp.today().normalize() -
                         pd.Timestamp(rec.get("asof", "2000-01-01")).normalize()).days <= 45
        if rec_ok:
            bias_state = "carried"
            carried_from = rec.get("asof", "")
            if lang == "en":
                data_note = f"Macro data missing; carrying over bias from {carried_from}"
            else:
                data_note = f"Macro data missing; carrying over bias from {carried_from}"
            score = float(rec.get("score", 0.0))
            norm = score / 5.0
            bias = int(rec.get("bias", 0))
        else:
            bias_state = "unknown"
            data_note = ("Macro data missing and no prior bias to carry; bias unreliable"
                         if lang == "en" else
                         "Macro data missing and no prior bias to carry; bias unreliable")
            bias = 0
    else:
        bias = 1 if score >= thr else (-1 if score <= -thr else 0)
        if use_network:   # Only the live path saves the historical bias; offline/manual mode does not overwrite
            _save_last_bias({"bias": int(bias), "score": round(float(score), 2),
                             "asof": pd.Timestamp.today().strftime("%Y-%m-%d %H:%M")})

    label = {1: "Long bias", -1: "Short bias", 0: "Neutral"}[bias]
    # Size multiplier is scaled by the "signed" driver strength: amplified when the driver agrees with position direction, reduced when opposite.
    # The old implementation used abs(norm), which amplified size when the driver was bearish (score<0) -- the direction was inverted.
    size_mult = float(np.clip(1.0 + 0.25 * norm, 0.5, 1.75))

    return {
        "score": round(float(score), 2),
        "norm": round(float(norm), 3),
        "bias": bias,
        "label": label,
        "size_mult": round(size_mult, 2),
        "threshold": thr,
        "parts": parts,
        "asof": pd.Timestamp.today().strftime("%Y-%m-%d %H:%M"),
        "bias_state": bias_state,
        "coverage": round(float(coverage), 2),
        "macro_cov": round(float(macro_cov), 2),
        "carried_from": carried_from,
        "data_note": data_note,
    }


def to_text(res: Dict, lang: str = "zh") -> str:
    st = res.get("bias_state", "ok")
    if lang == "en":
        label = {1: "Long bias", -1: "Short bias", 0: "Neutral"}.get(res.get("bias", 0), "Neutral")
        head = f"Driver score {res['score']:+.2f} / 10   Conclusion: {label}   (threshold ±{res['threshold']})"
        if st == "carried":
            head += f"   (macro data missing; carried bias from {res.get('carried_from','')})"
        elif st == "unknown":
            head += "   (data missing; bias unreliable)"
        lines = [head,
                 f"Size x{res['size_mult']}   Generated {res['asof']}"
                 f"   Coverage {res.get('coverage', 1.0):.0%}"
                 f"{'   Macro cov '+format(res.get('macro_cov',1.0),'.0%') if st!='ok' else ''}",
                 "",
                 f"{'Factor':<16}{'Weight':>7}{'Score':>9}   Note",
                 "-" * 80]
        name_en = {"geopolitics": "Geopolitics", "growth": "Growth", "real_rate": "Real rate",
                   "capital_flow": "Capital flow", "jewelry": "Jewelry", "industrial": "Industrial",
                   "central_bank": "Central bank"}
        for k, v in res["parts"].items():
            lines.append(f"{name_en.get(k, k):<16}{v['weight']:>7.1f}{v['score']:>+9.2f}   {v.get('note_en', v['note'])}")
        return "\n".join(lines)
    # ---- Chinese (default) ----
    head = f"Driver score {res['score']:+.2f} / 10   Conclusion: {res['label']}   (threshold ±{res['threshold']})"
    if st == "carried":
        head += f"   (macro data missing; carried bias from {res.get('carried_from','')})"
    elif st == "unknown":
        head += "   (data missing; bias unreliable)"
    lines = [head,
             f"Size x{res['size_mult']}   Generated {res['asof']}"
             f"   Coverage {res.get('coverage', 1.0):.0%}"
             f"{'   Macro cov '+format(res.get('macro_cov',1.0),'.0%') if st!='ok' else ''}",
             "",
             f"{'Factor':<14}{'Weight':>6}{'Score':>8}   Note",
             "-" * 78]
    name_cn = {"geopolitics": "Geopolitics", "growth": "Growth", "real_rate": "Real rate",
               "capital_flow": "Capital flow", "jewelry": "Jewelry", "industrial": "Industrial",
               "central_bank": "Central bank"}
    for k, v in res["parts"].items():
        lines.append(f"{name_cn.get(k, k):<14}{v['weight']:>6.1f}{v['score']:>+8.2f}   {v['note']}")
    return "\n".join(lines)
