#!/usr/bin/env python
"""Dina Gold Trading System - main entry point (Python side).

Pipeline: load market data -> assemble indicators/patterns -> five-condition signals
          -> driver analysis -> backtest -> historical statistics
          -> output output/report.html + output/gold_signal.ini (for the MT5 EA)

Usage:
  python run_daily.py                        # Daemon: run once on startup, then trigger daily at 08:00
  python run_daily.py --once                 # Run once and exit (manual trigger / debugging)
  python run_daily.py --run-hour 7 --run-min 30   # Change the trigger time
  python run_daily.py --source yfinance      # Specify the data source
  python run_daily.py --offline              # No network: use only cache/CSV + manual fundamentals
  python run_daily.py --mt5-files "C:/Users/.../MQL5/Files"   # Write signals directly into MT5
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gt import analytics as AN
from gt import backtest as BT
from gt import data as GD
from gt import fundamental as FU
from gt import report as RP
from gt import signals as SG
from gt.config import load_config, project_root


_LOG_PATH = os.path.join("output", "run_daily.log")


class _Tee:
    """Also write a copy of stdout/stderr to a log file, for later inspection of what the daemon ran."""
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._f = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, s: str) -> None:
        try:
            sys.__stdout__.write(s)
        except Exception:
            pass
        try:
            self._f.write(s)
        except Exception:
            pass

    def flush(self) -> None:
        try:
            sys.__stdout__.flush()
        except Exception:
            pass
        try:
            self._f.flush()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass
    """同时把 stdout/stderr 写一份到日志文件，方便事后查守护进程跑过什么。"""
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._f = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, s: str) -> None:
        try:
            sys.__stdout__.write(s)
        except Exception:
            pass
        try:
            self._f.write(s)
        except Exception:
            pass

    def flush(self) -> None:
        try:
            sys.__stdout__.flush()
        except Exception:
            pass
        try:
            self._f.flush()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass


_STOP = False


def _on_signal(sig: int, frame) -> None:                          # noqa: ARG001
    """Graceful SIGINT / SIGTERM shutdown: set _STOP and let the current step finish naturally."""
    global _STOP
    try:
        sys.__stdout__.write(f"\n[schedule] 收到停止信号 ({sig})，等待当前步骤结束…\n")
        sys.__stdout__.flush()
    except Exception:
        pass
    _STOP = True


def _fallback_series(n: int = 20000, seed: int = 7) -> pd.DataFrame:
    """Synthetic data used when offline (for pipeline flow only; not for real decisions)."""
    rng = np.random.default_rng(seed)
    t = pd.date_range(end=pd.Timestamp.now().floor("h"), periods=n, freq="h")
    ret = rng.normal(0, 0.0009, n) + 0.00002 * np.sin(np.arange(n) / 700.0)
    close = 1900 * np.exp(np.cumsum(ret))
    high = close * (1 + np.abs(rng.normal(0, 0.0006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.0006, n)))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"time": t, "open": open_, "high": high, "low": low,
                         "close": close, "volume": rng.integers(100, 1000, n)})


def _parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--source", default=None, choices=["auto", "mt5", "yfinance", "csv", "cache"])
    ap.add_argument("--csv", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--bars", type=int, default=None)
    ap.add_argument("--mt5-files", default=os.environ.get("MT5_FILES_PATH", ""))
    ap.add_argument("--no-backtest", action="store_true")
    ap.add_argument("--once", action="store_true",
                    help="只跑一次就退出（默认进入每日定时循环）")
    ap.add_argument("--run-hour", type=int, default=8,
                    help="每日触发时间（小时 0-23），默认 8")
    ap.add_argument("--run-min", type=int, default=0,
                    help="每日触发时间（分钟 0-59），默认 0")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"],
                    help="报告语言：zh=中文（默认）/ en=英文")
    return ap.parse_args(argv)


def _next_run(now: datetime, hh: int, mm: int) -> datetime:
    """Next trigger time: today at hh:mm (use tomorrow if that time has already passed)."""
    today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return today if now < today else today + timedelta(days=1)


def _sleep(seconds: float) -> bool:
    """Sleep in segments, checking _STOP every 60 seconds, so Ctrl+C stops within ~1 minute."""
    end = time.time() + seconds
    while not _STOP and time.time() < end:
        time.sleep(min(60.0, end - time.time()))
    return not _STOP


def run_once(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    root = project_root()
    out_dir = os.path.join(root, cfg["output"]["dir"])
    os.makedirs(out_dir, exist_ok=True)

    symbol = args.symbol or cfg["symbol"]
    src = args.source or cfg["data"]["source"]
    if args.csv:
        src = "csv"
    bars = args.bars or cfg["data"]["bars"]

    warn = []
    # ---------------- Data ----------------
    if args.csv:
        h1 = GD._from_csv(args.csv)
        if h1 is None:
            print(f"[error] 读不到 CSV: {args.csv}")
            return 1
    else:
        try:
            h1 = GD.load_ohlc(symbol, "H1", bars, src,
                              args.csv or os.path.join(root, cfg["data"]["csv_path"]),
                              cfg["data"]["cache_dir"])
        except Exception as e:
            warn.append(f"行情获取失败（{e}），已使用<b>合成数据</b>跑通流程，结果不可用于交易决策。")
            h1 = _fallback_series(bars)
    h1 = h1.dropna().sort_values("time").reset_index(drop=True)
    h4 = GD.resample(h1, "H4")
    d1 = GD.resample(h1, "D1")
    print(f"[ok] H1={len(h1)} 根  {h1['time'].iloc[0]} ~ {h1['time'].iloc[-1]}")

    # ---------------- Indicators / Signals ----------------
    f = SG.prepare(h1, h4, d1, cfg)
    # Baseline backtest uses config (allow_short is controlled by config, keeping long-only comparison basis)
    sig = SG.entry_scores(f, cfg)
    # Report scan needs real long/short capability (consistent with EA's B3 regime), so override allow_short=True.
    # Otherwise the Python scan would show "0 shorts" as before, inconsistent with the live EA (InpAllowShort=true, which shorts)
    # and would mislead decisions. Baseline backtest still uses the config version above (long-only comparison).
    cfg_scan = dict(cfg)
    cfg_scan["entry"] = {**cfg.get("entry", {}), "allow_short": True}
    sig_scan = SG.entry_scores(f, cfg_scan)
    n_long_raw = int(sig_scan["sig_long"].sum())
    n_short_raw = int(sig_scan["sig_short"].sum())
    print(f"[ok] 技术触发信号：多 {n_long_raw} / 空 {n_short_raw}"
          f"（五要件原始触发，未经 B3 门控；基线回测仍用 config 的 long-only 口径）")

    # ---------------- Fundamentals ----------------
    try:
        fund = FU.analyze(cfg, use_network=not args.offline, lang=args.lang)
    except Exception as e:
        warn.append(f"基本面取数异常：{e}")
        fund = FU.analyze(cfg, use_network=False, lang=args.lang)
    print(FU.to_text(fund, lang=args.lang))

    # ---------------- Actual openable-signal stats after B3 gating ----------------
    # Gate technical triggers with "current bias × per-bar daily trend" (same logic as the EA live DinaRegimeGate),
    # showing how many historical technical signals are passed (long/short) vs. stood aside under the current fundamental framework.
    rc = cfg.get("regime", {})
    _span = rc.get("d1_span", cfg.get("trend_ema", 50))
    d1_trend = SG._align_d1_trend(f, d1, _span)
    _skew = float(cfg.get("entry", {}).get("regime_skew_factor", 0.40))
    _nlo = bool(cfg.get("entry", {}).get("regime_neutral_long_only", True))
    _nfa = bool(cfg.get("entry", {}).get("regime_neutral_flat_aside", True))
    _b = int(fund.get("bias", 0))
    _al = d1_trend.apply(lambda t: SG.regime_decision(_b, int(t), _skew, _nlo, _nfa)[0])
    _ash = d1_trend.apply(lambda t: SG.regime_decision(_b, int(t), _skew, _nlo, _nfa)[1])
    b3_long = int((sig_scan["sig_long"] & _al).sum())
    b3_short = int((sig_scan["sig_short"] & _ash).sum())
    b3_aside = int(((sig_scan["sig_long"] | sig_scan["sig_short"]) & ~(_al | _ash)).sum())
    print(f"[ok] B3门控后(偏置={_b:+d}, 当前框架)：放行多 {b3_long} / 放行空 {b3_short} / 站旁边 {b3_aside}")
    n_sig = b3_long + b3_short

    # Latest World Gold Council research news (gold.org; display only, not used for scoring)
    news = []
    try:
        from gt import goldorg as GO
        news = GO.fetch_news(limit=8)
    except Exception:
        news = []

    fund_table = pd.DataFrame([{
        "因子": k, "权重": v["weight"], "得分": round(v["score"], 2),
        "说明": v.get("note_en", v["note"]) if args.lang == "en" else v["note"]}
        for k, v in fund["parts"].items()])

    # ---------------- Backtest ----------------
    metrics, equity, trades_df = {}, None, pd.DataFrame()
    kelly_f = 0.0
    kelly = 0.0
    ctx_seg = None
    if not args.no_backtest:
        bt_start = cfg["backtest"].get("start")
        mask = pd.Series(True, index=f.index)
        if bt_start:
            mask = f["time"] >= pd.Timestamp(bt_start)
        if cfg["backtest"].get("end"):
            mask &= f["time"] <= pd.Timestamp(cfg["backtest"]["end"])
        sub = f[mask].reset_index(drop=True)
        ssub = sig[mask.to_numpy()].reset_index(drop=True)

        # Baseline performance uses the "pure technical system" basis: do not let today's fundamental bias veto historical signals
        # (fundamental bias only acts as a filter in live trading / the signal file)
        r1 = BT.run(sub, cfg, ssub, bias=0, size_mult=1.0, veto=False,
                    initial_capital=cfg["backtest"]["initial_capital"])
        kelly_f = r1.metrics.get("凯利建议f*", 0.0)
        kelly = 0.0
        if cfg["risk"].get("kelly_enabled") and kelly_f > 0:
            kelly = min(kelly_f * cfg["risk"]["kelly_safety"], cfg["risk"]["kelly_cap"])
        metrics = r1.metrics
        equity = r1.equity
        trades_df = BT.trades_df(r1.trades)

        # By year (same basis)
        rows = []
        for y in sorted(set(sub["time"].dt.year)):
            my = (sub["time"].dt.year == y).to_numpy()
            ry = BT.run(sub[my].reset_index(drop=True), cfg, ssub[my].reset_index(drop=True),
                        initial_capital=100000.0)
            mm = ry.metrics
            if mm.get("交易次数", 0) < 2:
                continue
            rows.append({"区间": str(y), "交易次数": mm["交易次数"], "胜率": mm["胜率"],
                         "盈亏比": mm["风险报酬率(盈亏比)"], "盈利因子": mm["盈利因子"],
                         "年化": mm["年化(CAGR)"], "最大回撤": mm["最大回撤"], "夏普": mm["夏普"]})
        ctx_seg = pd.DataFrame(rows) if rows else None

    # ---------------- Historical data analysis ----------------
    seas = AN.seasonality(f)
    ctx = {
        "subtitle": f"品种 {symbol} ｜ 1H 主周期 ｜ 数据 {h1['time'].iloc[0]:%Y-%m-%d} ~ "
                    f"{h1['time'].iloc[-1]:%Y-%m-%d} ｜ 样本 {len(h1)} 根 ｜ "
                    f"B3可开仓 {n_sig} 次（技术触发 多{n_long_raw}/空{n_short_raw}）",
        "fundamental": fund, "fund_table": fund_table, "metrics": metrics,
        "equity": equity,
        "season_month": seas.get("月份"), "season_dow": seas.get("星期"),
        "session": AN.session_stats(f), "conv": AN.convergence_stats(f),
        "attr": AN.condition_attribution(f, sig_scan), "fwd": AN.signal_forward_stats(f, sig_scan),
        "news": news, "news_source": "gold.org（World Gold Council）研究库",
        "seg": ctx_seg,
        "recent_trades": trades_df.tail(30) if not trades_df.empty else None,
        "warn": "；".join(warn) if warn else None,
    }

    # ---------------- Current state / MT5 signal ----------------
    i = len(f) - 1
    st = sig_scan.iloc[i]
    cur = pd.DataFrame([{
        "时间": f["time"].iloc[i], "收盘": round(float(f["close"].iloc[i]), 2),
        "ATR": round(float(f["atr"].iloc[i]), 2),
        "布林上轨": round(float(f["bb_up"].iloc[i]), 2),
        "布林中轨": round(float(f["bb_mid"].iloc[i]), 2),
        "布林下轨": round(float(f["bb_lo"].iloc[i]), 2),
        "顾比状态": {1: "金叉(多)", -1: "死叉(空)", 0: "未定"}.get(int(f["g_state"].iloc[i])),
        "回档": "多" if st["c1_pullback"] > 0 else ("空" if st["c1_pullback"] < 0 else "-"),
        "收口/乖离": bool(st["c2_band"]), "过度": bool(st["c3_over"]),
        "适离": bool(st["c4_level"]), "渐短": bool(st["c5_shrink"]),
        "多头分": int(st["score_long"]), "空头分": int(st["score_short"]),
    }])
    ctx["current"] = cur

    hi, lo = float(f["leg_high"].iloc[i]), float(f["leg_low"].iloc[i])
    rng = (hi - lo) if np.isfinite(hi) and np.isfinite(lo) else 0.0
    d = int(f["leg_dir"].iloc[i])
    levels = {
        "atr": round(float(f["atr"].iloc[i]), 3),
        "bb_up": round(float(f["bb_up"].iloc[i]), 2),
        "bb_mid": round(float(f["bb_mid"].iloc[i]), 2),
        "bb_lo": round(float(f["bb_lo"].iloc[i]), 2),
        "guppy_state": int(f["g_state"].iloc[i]),
        "pivot_p": round(float(f["lv0"].iloc[i]), 2) if np.isfinite(f["lv0"].iloc[i]) else 0.0,
        "pivot_r1": round(float(f["lv1"].iloc[i]), 2) if np.isfinite(f["lv1"].iloc[i]) else 0.0,
        "pivot_s1": round(float(f["lv2"].iloc[i]), 2) if np.isfinite(f["lv2"].iloc[i]) else 0.0,
        "fib_382": round((hi - 0.382 * rng) if (d == 1 and rng) else (lo + 0.382 * rng), 2),
        "fib_618": round((hi - 0.618 * rng) if (d == 1 and rng) else (lo + 0.618 * rng), 2),
        "last_price": round(float(f["close"].iloc[i]), 2),
    }
    ini_path = os.path.join(out_dir, cfg["output"]["signal_file"])
    dt_cur = int(f["d1_trend"].iloc[i]) if "d1_trend" in f.columns else 0
    rg = SG.regime_decision(fund.get("bias", 0), dt_cur,
                            float(cfg["entry"].get("regime_skew_factor", 0.4)),
                            bool(cfg["entry"].get("regime_neutral_long_only", True)),
                            bool(cfg["entry"].get("regime_neutral_flat_aside", True)))
    # Regime text follows the report language (written to ini and shown in the report)
    if (not rg[0]) and (not rg[1]):
        regime_zh, regime_en = "站旁边", "Stand aside"
    elif rg[0] and not rg[1]:
        regime_zh, regime_en = "只多", "Long only"
    elif rg[1] and not rg[0]:
        regime_zh, regime_en = "只空", "Short only"
    else:
        regime_zh, regime_en = ("多>空", "Long>Short") if rg[2] > rg[3] else ("空>多", "Short>Long")
    regime_txt = regime_en if args.lang == "en" else regime_zh
    ini_txt = RP.export_signal_ini(ini_path, fund, levels,
                                   {"veto": cfg["fundamental"].get("veto_enabled", True),
                                    "kelly": round(kelly, 4), "kelly_raw": round(kelly_f, 4),
                                    "d1_trend": dt_cur, "regime": regime_txt},
                                   lang=args.lang)
    ctx["signal_ini"] = ini_txt
    if args.mt5_files and os.path.isdir(args.mt5_files):
        shutil.copy(ini_path, os.path.join(args.mt5_files, cfg["output"]["signal_file"]))
        print(f"[ok] 信号已写入 {args.mt5_files}")

    # ---------------- Report ----------------
    html = RP.render(ctx, lang=args.lang)
    rep = os.path.join(out_dir, cfg["output"]["report_file"])
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[ok] 报告 -> {rep}")
    print(f"[ok] 信号 -> {ini_path}")
    return 0


def run_loop(args: argparse.Namespace) -> int:
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    print(f"[schedule] 帝娜黄金守护进程启动  触发时间 每天 {args.run_hour:02d}:{args.run_min:02d}")
    print(f"[schedule] 日志同步写入 {os.path.join(project_root(), _LOG_PATH)}  Ctrl+C 优雅停止")
    print(f"[schedule] 启动时先跑一次，给即时反馈")

    while not _STOP:
        started = datetime.now()
        try:
            run_once(args)
        except Exception as e:
            print(f"[error] 本次运行异常: {e!r}")
        print(f"[schedule] 本次完成于 {datetime.now():%Y-%m-%d %H:%M:%S}  用时 {(datetime.now()-started).total_seconds():.1f}s")

        # Schedule next run
        nxt = _next_run(datetime.now(), args.run_hour, args.run_min)
        secs = (nxt - datetime.now()).total_seconds()
        print(f"[schedule] 下次运行 {nxt:%Y-%m-%d %H:%M:%S}  等待 {secs/3600:.1f} 小时")
        if not _sleep(secs):
            break
        print(f"[schedule] {datetime.now():%Y-%m-%d %H:%M:%S} 触发每日运行")

    print("[schedule] 已退出")
    return 0


def main() -> int:
    args = _parse_args()
    if not args.once:
        # Daemon mode: write logs under output/ at project root, same dir as report.html
        log_path = os.path.join(project_root(), _LOG_PATH)
        sys.stdout = _Tee(log_path)
        sys.stderr = sys.stdout
    if args.once:
        return run_once(args)
    return run_loop(args)


if __name__ == "__main__":
    raise SystemExit(main())
