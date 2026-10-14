"""Market and macro data loading.

Priority: MT5 (Windows) -> yfinance -> local CSV.
Results are cached under data/cache so repeated runs are instant.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

import numpy as np
import pandas as pd

from .config import project_root

_TF_MAP = {"M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440, "W1": 10080}


# --------------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------------
def _mt5_path(csv_path=None) -> str | None:
    p = os.environ.get("MT5_PATH", "")
    if p:
        return p
    import glob
    cands = glob.glob(r"C:\Program Files\MetaTrader 5*\terminal64.exe") + \
            glob.glob(r"C:\Program Files (x86)\MetaTrader 5*\terminal64.exe")
    return cands[0] if cands else None


def _from_mt5(symbol: str, tf: str, bars: int) -> Optional[pd.DataFrame]:
    try:
        import MetaTrader5 as mt5
    except Exception:
        return None
    tf_const = {
        "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
    }.get(tf)
    if tf_const is None:
        return None
    if not mt5.initialize(path=_mt5_path()):
        return None
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            for alt in (symbol + ".m", symbol + "m", "GOLD", symbol + ".raw", symbol + ".pro"):
                if mt5.symbol_info(alt) is not None:
                    symbol = alt
                    break
        if not mt5.symbol_select(symbol, True):
            return None
        rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, bars)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})
        return df[["time", "open", "high", "low", "close", "volume"]]
    finally:
        mt5.shutdown()


def _from_mt5_range(symbol: str, tf: str, start, end) -> Optional[pd.DataFrame]:
    """Fetch OHLC from MT5 over a date range (solves the "last N bars" problem of an unfixed start point)."""
    try:
        import MetaTrader5 as mt5
    except Exception:
        return None
    tf_const = {
        "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
    }.get(tf)
    if tf_const is None:
        return None
    if not mt5.initialize(path=_mt5_path()):
        return None
    try:
        if mt5.symbol_info(symbol) is None:
            for alt in (symbol + ".m", symbol + "m", "GOLD", symbol + ".raw", symbol + ".pro"):
                if mt5.symbol_info(alt) is not None:
                    symbol = alt
                    break
        if not mt5.symbol_select(symbol, True):
            return None
        s = pd.Timestamp(start).to_pydatetime()
        e = pd.Timestamp(end).to_pydatetime()
        rates = mt5.copy_rates_range(symbol, tf_const, s, e)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})
        return df[["time", "open", "high", "low", "close", "volume"]]
    finally:
        mt5.shutdown()


def load_ohlc_range(symbol: str, tf: str = "H1", start="2021-01-01", end=None,
                    cache_dir: str = "data/cache") -> pd.DataFrame:
    """Load OHLC over a date range, with parquet caching (the cache key includes start/end dates)."""
    cache_root = cache_dir if os.path.isabs(cache_dir) else os.path.join(project_root(), cache_dir)
    os.makedirs(cache_root, exist_ok=True)
    sd = pd.Timestamp(start).strftime("%Y%m%d")
    ed = (pd.Timestamp(end) if end is not None else pd.Timestamp.today()).strftime("%Y%m%d")
    cache_file = os.path.join(cache_root, f"{symbol}_{tf}_{sd}_{ed}.parquet")
    if os.path.exists(cache_file):
        try:
            return norm_time(pd.read_parquet(cache_file))
        except Exception:
            pass
    df = _from_mt5_range(symbol, tf, start, end)
    if df is None or df.empty:
        raise RuntimeError(f"failed to fetch {symbol} {tf} {start}~{end} (MT5 range fetch attempted)")
    df = norm_time(df.dropna().sort_values("time").reset_index(drop=True))
    try:
        df.to_parquet(cache_file, index=False)
    except Exception:
        pass
    return df


def _from_yfinance(symbol: str, tf: str, bars: int) -> Optional[pd.DataFrame]:
    try:
        import yfinance as yf
    except Exception:
        return None
    # yfinance only provides intraday <=60m and daily; H4 is resampled from H1
    yf_tf = {"M5": "5m", "M15": "15m", "M30": "30m", "H1": "60m",
             "H4": "60m", "D1": "1d", "W1": "1wk"}.get(tf, "60m")
    period = {"M5": "60d", "M15": "60d", "M30": "60d", "H1": "730d",
              "H4": "730d", "D1": "max", "W1": "max"}.get(tf, "730d")
    try:
        df = yf.download(symbol, interval=yf_tf, period=period,
                         auto_adjust=False, progress=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df = df.reset_index()
    col = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={col: "time", "Open": "open", "High": "high",
                            "Low": "low", "Close": "close", "Volume": "volume"})
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    keep = [c for c in ["time", "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_localize(None)
    if tf == "H4":
        df = resample(df, "H4")
    return df.tail(bars).reset_index(drop=True)


def _from_csv(path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    ren = {}
    for need in ["time", "open", "high", "low", "close"]:
        for alt in (need, need.capitalize(), "Date", "datetime", "Timestamp"):
            if alt in cols:
                ren[cols[alt]] = need
                break
    df = df.rename(columns=ren)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["time"] = pd.to_datetime(df["time"])
    return df[["time", "open", "high", "low", "close", "volume"]].sort_values("time").reset_index(drop=True)


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    if df is None or df.empty or tf == "H1":
        return df
    minutes = _TF_MAP.get(tf, 60)
    out = (df.set_index("time")
             .resample(f"{minutes}min")
             .agg({"open": "first", "high": "max", "low": "min",
                   "close": "last", "volume": "sum"})
             .dropna()
             .reset_index())
    return norm_time(out)


# pandas 2.x time defaults to ns, 3.x to us; mismatched dtypes on both sides make merge_asof throw directly
# MergeError. Project-wide we pin the time column to ms to avoid cross-version pandas pitfalls.
DT = "datetime64[ms]"


def norm_time(df: pd.DataFrame, col: str = "time") -> pd.DataFrame:
    """Normalize the time column to datetime64[ms] (in place; returns the same object)."""
    if df is not None and col in getattr(df, "columns", []):
        df[col] = pd.to_datetime(df[col], errors="coerce").astype(DT)
    return df


def _best_cache(symbol: str, tf: str, cache_root: str, bars: int = 20000):
    """Among all {symbol}_{tf}*.parquet caches, pick the one with the latest last timestamp
(including range caches like XAUUSD_H1_20210101_20260926.parquet); return its tail(bars).
Return None if none found.

Fixes "stale quotes": the old load_ohlc only read the fixed name XAUUSD_H1.parquet, so once it
went stale it never refreshed; now the fresher range cache is preferred, avoiding reports frozen two weeks back.
"""
    import glob
    pats = [os.path.join(cache_root, f"{symbol}_{tf}.parquet"),
            os.path.join(cache_root, f"{symbol}_{tf}_*.parquet")]
    files = set()
    for p in pats:
        files.update(glob.glob(p))
    best, best_last = None, None
    for fp in files:
        try:
            df = norm_time(pd.read_parquet(fp))
        except Exception:
            continue
        if df is None or len(df) <= 200 or "time" not in df.columns:
            continue
        last = pd.Timestamp(df["time"].iloc[-1])
        if best is None or last > best_last:
            best, best_last = df.tail(bars).reset_index(drop=True), last
    return best


def load_ohlc(symbol: str, tf: str = "H1", bars: int = 20000,
              source: str = "auto", csv_path: Optional[str] = None,
              cache_dir: str = "data/cache") -> pd.DataFrame:
    """Load OHLC with parquet caching.

Cache strategy (fixes "quotes stuck at 9-18"):
  - source=cache: read the freshest cache directly, no network.
  - source=auto/mt5/yfinance/csv: prefer live fetch (MT5 > Yahoo > CSV); on success refresh and
    return the named cache; if all live sources fail (offline / rate-limited) fall back to the
    freshest cache (including range caches) instead of being stuck on the stale XAUUSD_H1.parquet.

Effect: when MT5 is available on the user's machine, data auto-refreshes to the current day daily;
in a sandbox / offline it still uses range caches to keep data relatively fresh, eliminating the
"report frozen two weeks back" issue.
"""
    cache_root = cache_dir if os.path.isabs(cache_dir) else os.path.join(project_root(), cache_dir)
    os.makedirs(cache_root, exist_ok=True)
    cache_file = os.path.join(cache_root, f"{symbol}_{tf}.parquet")

    if source == "cache":
        df = _best_cache(symbol, tf, cache_root, bars)
        if df is None:
            raise RuntimeError(f"no {symbol} {tf} cache available (source=cache)")
        return df

    # auto / mt5 / yfinance / csv: prefer live data
    df = None
    order = {"auto": ["mt5", "yfinance", "csv"],
             "mt5": ["mt5"], "yfinance": ["yfinance"], "csv": ["csv"]}[source]
    yf_symbol = "GC=F" if symbol.upper().startswith("XAU") else symbol
    for src in order:
        if src == "mt5":
            df = _from_mt5(symbol, tf, bars)
        elif src == "yfinance":
            df = _from_yfinance(yf_symbol, tf, bars)
        else:
            df = _from_csv(csv_path or "")
        if df is not None and len(df) > 200:
            break
        df = None

    if df is not None and len(df) > 200:
        df = norm_time(df.dropna().sort_values("time").reset_index(drop=True))
        try:
            df.to_parquet(cache_file, index=False)
        except Exception:
            pass
        return df.tail(bars).reset_index(drop=True)

    # all live sources failed -> fall back to the freshest cache (range cache included)
    cached = _best_cache(symbol, tf, cache_root, bars)
    if cached is not None:
        print(f"[warn] live quote fetch failed (tried {order}), fell back to local cache"
              f" (data as of {cached['time'].iloc[-1]:%Y-%m-%d})")
        return cached
    raise RuntimeError(f"failed to fetch {symbol} {tf} data (tried {order}, and no cache available)")


def load_multi(symbol: str, tfs=("H1", "H4", "D1"), bars: int = 20000,
               source: str = "auto", csv_path: Optional[str] = None,
               cache_dir: str = "data/cache") -> Dict[str, pd.DataFrame]:
    out = {}
    for tf in tfs:
        try:
            out[tf] = load_ohlc(symbol, tf, bars, source, csv_path, cache_dir)
        except Exception as e:
            print(f"[warn] {tf} load failed: {e}")
    return out


# --------------------------------------------------------------------------
# Macro / fundamentals
# --------------------------------------------------------------------------
def _cache_path(name: str, cache_dir: str = "data/cache") -> str:
    """In-project cache file path (auto-converts absolute/relative)."""
    root = cache_dir if os.path.isabs(cache_dir) else os.path.join(project_root(), cache_dir)
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, name)


def _cache_read_series(fp: str) -> Optional[pd.Series]:
    """Read a cached local time series; return None if missing or corrupt."""
    if not os.path.exists(fp):
        return None
    try:
        c = pd.read_csv(fp, index_col=0, parse_dates=True)
        s = c.iloc[:, 0] if c.shape[1] >= 1 else c.squeeze()
        s.index = pd.to_datetime(s.index, errors="coerce")
        s = s.dropna()
        return s if len(s) > 0 else None
    except Exception:
        return None


def _cache_write_series(fp: str, s: pd.Series) -> None:
    """Persist a time series to disk cache (overwrite)."""
    try:
        ss = s.copy()
        ss.index = pd.to_datetime(ss.index, errors="coerce")
        ss = ss.dropna()
        ss.rename("value").to_frame().to_csv(fp)
    except Exception:
        pass


def fred_series(series_id: str, start: str = "2015-01-01") -> Optional[pd.Series]:
    """FRED's API-key-free CSV endpoint.

With a local-cache fallback: try a live fetch first and refresh the cache on success; on failure /
rate-limit, fall back to the last successful cache file. This way, even if the machine cannot reach
FRED (firewall / rate-limit), the fundamental macro factors can still be read from local cache,
avoiding the bias being silently diluted to neutral.
"""
    fp = _cache_path(f"fred_{series_id}.csv")
    s = _fred_series_live(series_id)
    if s is not None and len(s) > 0:
        _cache_write_series(fp, s)
        return s[s.index >= start]
    c = _cache_read_series(fp)
    if c is not None and len(c) > 0:
        return c[c.index >= start]
    return None


def _fred_series_live(series_id: str) -> Optional[pd.Series]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        df = pd.read_csv(url)
    except Exception:
        return None
    if df.empty or series_id not in df.columns:
        return None
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().set_index("date")["value"]


def _http_get_csv(url: str, timeout: int = 20) -> Optional[pd.DataFrame]:
    """Prefetch via urllib and hand the result to pd.read_csv for parsing.
pandas 3.x removed pd.read_csv(timeout=...), so a request-level timeout is no longer possible;
we use urllib instead - it allows a timeout and adds a User-Agent to avoid being rejected by the CDN."""
    import io as _io
    import urllib.request as _ur
    try:
        req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0 (gold-trader)"})
        with _ur.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except Exception:
        return None
    if not data:
        return None
    try:
        return pd.read_csv(_io.BytesIO(data))
    except Exception:
        return None


def cboe_vix(start: str = "2015-01-01", timeout: int = 20) -> Optional[pd.Series]:
    """CBOE official VIX historical CSV. The original publisher of the VIX index - most authoritative,
key-free, data from 1990.

With a local-cache fallback: on live failure (CDN blocked / timeout) fall back to the last successful
cache, avoiding VIX absence that would zero out the geo-politics factor score and silently dilute
the bias to neutral.
"""
    fp = _cache_path("cboe_vix.csv")
    s = _cboe_vix_live(start, timeout)
    if s is not None and len(s) > 0:
        _cache_write_series(fp, s)
        return s
    c = _cache_read_series(fp)
    if c is not None and len(c) > 0:
        return c[c.index >= start] if start else c
    return None


def _cboe_vix_live(start: str, timeout: int) -> Optional[pd.Series]:
    url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    df = _http_get_csv(url, timeout=timeout)
    if df is None or df.empty or "CLOSE" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y", errors="coerce")
    df["value"] = pd.to_numeric(df["CLOSE"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).set_index("date")["value"]
    return df[df.index >= start] if start else df


def yf_close(ticker: str, period: str = "2y", cache_dir: str = "data/cache") -> Optional[pd.Series]:
    """Fetch closing prices. yfinance is easily rate-limited (429), so results are cached to disk and
fall back to cache on network failure."""
    cache_root = cache_dir if os.path.isabs(cache_dir) else os.path.join(project_root(), cache_dir)
    os.makedirs(cache_root, exist_ok=True)
    safe = "".join(ch if ch.isalnum() else "_" for ch in ticker)
    fp = os.path.join(cache_root, f"yf_{safe}.csv")

    s = None
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, auto_adjust=False, progress=False)["Close"]
        if df is not None and not df.empty:
            df = df.copy()
            df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
            if isinstance(df, pd.DataFrame):
                df = df.iloc[:, 0]
            s = df.dropna()
    except Exception:
        s = None

    if s is not None and len(s) > 0:
        try:
            s.to_frame("close").to_csv(fp)
        except Exception:
            pass
        return s

    if os.path.exists(fp):                       # network failed -> fall back to last successful cache
        try:
            c = pd.read_csv(fp, index_col=0, parse_dates=True)["close"]
            return c.dropna()
        except Exception:
            return None
    return None


def stale_days(s: Optional[pd.Series]) -> Optional[int]:
    """Number of calendar days from the last bar of the series to today, used to judge staleness."""
    if s is None or len(s) == 0:
        return None
    try:
        return int((pd.Timestamp.today().normalize() - pd.Timestamp(s.index[-1]).tz_localize(None).normalize()).days)
    except Exception:
        return None


def _zscore_last(s: pd.Series, window: int = 250) -> float:
    """Percentile of the latest value within the past window (coarse mapping to -2..+2)."""
    if s is None or len(s) < 30:
        return 0.0
    v = float(s.iloc[-1])
    hist = s.iloc[-(window + 1):-1]
    mu, sd = float(hist.mean()), float(hist.std(ddof=0))
    if sd == 0 or not np.isfinite(sd):
        return 0.0
    z = (v - mu) / sd
    return float(np.clip(z, -2.0, 2.0))
