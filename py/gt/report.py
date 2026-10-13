"""Report rendering (pure HTML + inline SVG, no frontend dependency) and MT5 signal-file export."""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ------------------------------------------------------- i18n ------------
# Fixed bilingual text (zh=default, en=English report). Variable names/logic unchanged, only display strings.
_I18N = {
    "zh": {
        "title": "帝娜黄金交易系统 · 分析报告",
        "sec1": "一、驱动分析（基本面）",
        "sec1b": "一·补、世界黄金协会最新研究",
        "sec2": "二、回测绩效（1小时图五要件）",
        "sec3": "三、历史数据分析",
        "s31": "3.1 季节性（月度）", "s32": "3.2 星期效应", "s33": "3.3 时段效应",
        "s34": "3.4 布林带敛散统计", "s35": "3.5 五要件单因子归因",
        "s36": "3.6 信号前瞻表现", "s37": "3.7 分年度表现",
        "sec4": "四、最近 30 笔交易",
        "sec5": "五、当前状态与 MT5 信号文件",
        "ini_h": "gold_signal.ini（复制到 MQL5/Files/）",
        "k_score": "驱动总分", "k_concl": "结论", "k_size": "仓位系数", "k_asof": "数据时点",
        "equity": "权益曲线", "month_ret": "月度平均后续收益 %",
        "no_data": "无数据", "src_label": "来源：",
        "ini1": "; 帝娜黄金交易系统 - Python 侧输出，供 MT5 EA 读取",
        "ini2": "; 基本面只做偏置/否决/仓位缩放，进场扳机始终是技术面的势位态",
    },
    "en": {
        "title": "Dina Gold Trading System · Analysis Report",
        "sec1": "1. Driver Analysis (Fundamentals)",
        "sec1b": "1b. Latest World Gold Council Research",
        "sec2": "2. Backtest Performance (1H Five Conditions)",
        "sec3": "3. Historical Data Analysis",
        "s31": "3.1 Seasonality (Monthly)", "s32": "3.2 Weekday Effect", "s33": "3.3 Session Effect",
        "s34": "3.4 Bollinger Convergence Stats", "s35": "3.5 Five-Condition Attribution",
        "s36": "3.6 Signal Forward Performance", "s37": "3.7 Yearly Performance",
        "sec4": "4. Recent 30 Trades",
        "sec5": "5. Current Status & MT5 Signal File",
        "ini_h": "gold_signal.ini (copy to MQL5/Files/)",
        "k_score": "Driver Score", "k_concl": "Conclusion", "k_size": "Size Factor", "k_asof": "As of",
        "equity": "Equity Curve", "month_ret": "Monthly Avg Forward Return %",
        "no_data": "No data", "src_label": "Source: ",
        "ini1": "; Dina Gold Trading System - Python output, read by MT5 EA",
        "ini2": "; Fundamentals only set bias/veto/size; entry trigger is always the technical setup",
    },
}
# Backtest metric key mapping (English report only)
_METRICS_EN = {
    "交易次数": "Trades", "胜率": "Win%", "风险报酬率(盈亏比)": "Payoff",
    "盈利因子": "Profit Factor", "总收益率": "Total Return%", "年化(CAGR)": "CAGR%",
    "最大回撤": "Max Drawdown%", "夏普": "Sharpe", "凯利建议f*": "Kelly f*",
}
# Data-table column-name mapping (English report only; unlisted columns keep original names)
_COL_EN = {
    "因子": "Factor", "权重": "Weight", "得分": "Score", "说明": "Note",
    "持仓根数": "Hold Bars", "方向": "Direction", "信号数": "Signals",
    "平均收益": "Avg Ret%", "胜率%": "Win%", "中位收益%": "Median Ret%",
    "月份": "Month", "星期": "Weekday", "区间": "Period",
    "交易次数": "Trades", "盈亏比": "Payoff", "年化": "CAGR",
    "最大回撤": "Max DD", "夏普": "Sharpe", "盈利因子": "Profit Factor",
    "时间": "Time", "收盘": "Close", "ATR": "ATR",
    "布林上轨": "BB Up", "布林中轨": "BB Mid", "布林下轨": "BB Lo",
    "顾比状态": "Guppy", "回档": "Pullback",
    "收口/乖离": "Squeeze/Div", "过度": "Exhaust", "适离": "Proximity",
    "渐短": "Shrink", "决策": "Decision", "五要件": "Score",
    "开仓时间": "Open Time", "平仓时间": "Close Time", "手数": "Lots",
    "开仓价": "Open", "平仓价": "Close", "盈亏": "PnL", "盈亏R": "PnL R",
    "持有根数": "Bars", "原因": "Reason", "类型": "Type", "信号价": "Signal",
    "初始止损": "Init Stop", "要件分": "Score",
}
_BIAS_LABEL = {1: ("多头倾向", "Long bias"), -1: ("空头倾向", "Short bias"), 0: ("中性", "Neutral")}

# Data-table cell-value mapping (English report only: direction / five-condition names / offline notes / exit reasons / numbering, etc.)
_VAL_EN = (
    ("离线模式：仅手动项", "Offline: manual only"),
    ("大幅运动收盘破外轨", "Large move closes outer band"),
    ("小幅运动收盘反穿中轨", "Small move re-crosses mid"),
    ("反向进场信号", "Reverse entry signal"),
    ("时间止损", "Time stop"),
    ("回测结束", "Backtest end"),
    ("回档", "Pullback"), ("收口·乖离", "Squeeze/Div"), ("过度", "Exhaust"),
    ("适离", "Proximity"), ("渐短", "Shrink"), ("顾比", "Guppy"), ("布林", "Bollinger"),
    ("随机", "Stochastic"), ("斐波/轴心", "Fib/Pivot"), ("蜡烛", "Candle"),
    ("金叉", "Golden Cross"), ("死叉", "Death Cross"), ("未定", "Undecided"),
    ("只多", "Long only"), ("只空", "Short only"), ("站旁边", "Stand aside"),
    ("止损", "Stop Loss"),
    ("多", "Long"), ("空", "Short"), ("中性", "Neutral"),
    ("①", "1. "), ("②", "2. "), ("③", "3. "), ("④", "4. "), ("⑤", "5. "),
)


def _val_en(s: str) -> str:
    for a, b in _VAL_EN:
        s = s.replace(a, b)
    return s


# ---------------------------------------------------------------- SVG ----
def svg_line(series: pd.Series, width: int = 900, height: int = 260,
             color: str = "#c0392b", label: str = "", lang: str = "zh") -> str:
    if series is None or len(series) < 2:
        return f"<p>{_I18N.get(lang, _I18N['zh'])['no_data']}</p>"
    v = series.astype(float).to_numpy()
    lo, hi = float(np.nanmin(v)), float(np.nanmax(v))
    if hi == lo:
        hi = lo + 1
    pad = 40
    xs = np.linspace(pad, width - pad, len(v))
    ys = height - pad - (v - lo) / (hi - lo) * (height - 2 * pad)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{pad},{height-pad} " + pts + f" {width-pad},{height-pad}"
    grid = "".join(
        f'<line x1="{pad}" y1="{y:.1f}" x2="{width-pad}" y2="{y:.1f}" stroke="#e8eaed"/>'
        for y in np.linspace(pad, height - pad, 5))
    return f'''<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px">
  <rect width="{width}" height="{height}" fill="#fff"/>
  {grid}
  <polygon points="{area}" fill="{color}" opacity="0.08"/>
  <polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"/>
  <text x="{pad}" y="{pad-14}" font-size="13" fill="#5f6368">{label}  低 {lo:,.0f}  高 {hi:,.0f}</text>
</svg>'''


def svg_bars(df: pd.DataFrame, col: str, width: int = 900, height: int = 240,
             color: str = "#c0392b", label: str = "", lang: str = "zh") -> str:
    if df is None or df.empty:
        return f"<p>{_I18N.get(lang, _I18N['zh'])['no_data']}</p>"
    v = df[col].astype(float).to_numpy()
    keys = [str(i) for i in df.index]
    n = len(v)
    pos = np.all(v >= 0)
    lo, hi = (0, v.max()) if pos else (v.min(), v.max())
    if hi == lo:
        hi = lo + 1
    pad, bw = 40, max(6, (width - 2 * 40) / max(n, 1) * 0.7)
    zero_y = height - pad - (0 - lo) / (hi - lo) * (height - 2 * pad)
    bars = []
    for i, val in enumerate(v):
        x = pad + (width - 2 * pad) * (i + 0.5) / n - bw / 2
        y = height - pad - (val - lo) / (hi - lo) * (height - 2 * pad)
        h = abs(y - zero_y)
        top = min(y, zero_y)
        c = "#c0392b" if val >= 0 else "#1e8e3e"
        bars.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{c}" opacity="0.85"/>')
    labels = "".join(
        f'<text x="{pad + (width-2*pad)*(i+0.5)/n:.1f}" y="{height-pad+16}" font-size="10" '
        f'text-anchor="middle" fill="#5f6368">{k}</text>' for i, k in enumerate(keys))
    return f'''<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px">
  <rect width="{width}" height="{height}" fill="#fff"/>
  <line x1="{pad}" y1="{zero_y:.1f}" x2="{width-pad}" y2="{zero_y:.1f}" stroke="#9aa0a6"/>
  {''.join(bars)}{labels}
  <text x="{pad}" y="{pad-14}" font-size="13" fill="#5f6368">{label}</text>
</svg>'''


def df_html(df: Optional[pd.DataFrame], index: bool = True, lang: str = "zh") -> str:
    if df is None or df.empty:
        return f"<p>{_I18N.get(lang, _I18N['zh'])['no_data']}</p>"
    if lang == "en" and isinstance(df, pd.DataFrame):
        df = df.rename(columns={c: _COL_EN.get(c, c) for c in df.columns})
        if not df.empty:
            df = df.apply(lambda col: col.map(lambda v: _val_en(v) if isinstance(v, str) else v))
            if getattr(df.index, "dtype", None) is not None and df.index.dtype == object:
                df.index = pd.Index([_val_en(str(x)) for x in df.index])
    return df.to_html(index=index, border=0, classes="tbl", float_format=lambda x: f"{x:,.2f}")


# ------------------------------------------------------------- HTML ------
_CSS = """
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f6f7f9;
     color:#202124;margin:0;padding:28px;line-height:1.6}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:19px;margin:34px 0 10px;padding-left:10px;border-left:4px solid #c0392b}
h3{font-size:15px;margin:20px 0 8px;color:#3c4043}
.sub{color:#5f6368;font-size:13px;margin-bottom:20px}
.card{background:#fff;border:1px solid #e3e5e8;border-radius:10px;padding:18px 20px;margin:12px 0}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{background:#f1f3f4;text-align:right;padding:7px 10px;border-bottom:1px solid #e3e5e8;font-weight:600}
.tbl th:first-child,.tbl td:first-child{text-align:left}
.tbl td{padding:6px 10px;border-bottom:1px solid #f1f3f4;text-align:right}
.tbl tr:hover td{background:#fafbfc}
.kpis{display:flex;flex-wrap:wrap;gap:12px}
.kpi{flex:1;min-width:130px;background:#fff;border:1px solid #e3e5e8;border-radius:10px;padding:12px 14px}
.kpi .k{font-size:12px;color:#5f6368}
.kpi .v{font-size:21px;font-weight:600;margin-top:2px}
.up{color:#c0392b}.dn{color:#1e8e3e}
pre{background:#f8f9fa;border:1px solid #e3e5e8;border-radius:8px;padding:12px;
    font-size:12px;white-space:pre-wrap;font-family:Consolas,monospace}
.note{background:#fff8e1;border-left:4px solid #f9ab00;padding:10px 14px;font-size:13px;border-radius:0 8px 8px 0}
"""


def render(ctx: Dict, lang: str = "zh") -> str:
    T = _I18N.get(lang, _I18N["zh"])
    m = ctx.get("metrics", {})
    if lang == "en":
        m = {_METRICS_EN.get(k, k): v for k, v in m.items()}
    fund = ctx.get("fundamental", {})
    parts = []
    a = f"<h1>{T['title']}</h1><div class='sub'>{ctx.get('subtitle','')}</div>"

    # Driver analysis
    parts.append(f"<h2>{T['sec1']}</h2>")
    bl = _BIAS_LABEL.get(fund.get("bias", 0), ("中性", "Neutral"))[1 if lang == "en" else 0]
    cls = "up" if fund.get("bias", 0) > 0 else ("dn" if fund.get("bias", 0) < 0 else "")
    parts.append(
        f"<div class='card'><div class='kpis'>"
        f"<div class='kpi'><div class='k'>{T['k_score']}</div><div class='v {cls}'>{fund.get('score',0):+.2f}</div></div>"
        f"<div class='kpi'><div class='k'>{T['k_concl']}</div><div class='v {cls}'>{bl}</div></div>"
        f"<div class='kpi'><div class='k'>{T['k_size']}</div><div class='v'>{fund.get('size_mult',1)}</div></div>"
        f"<div class='kpi'><div class='k'>{T['k_asof']}</div><div class='v' style='font-size:14px'>{fund.get('asof','')}</div></div>"
        f"</div><div style='margin-top:12px'>{df_html(ctx.get('fund_table'), lang=lang)}</div></div>")

    # World Gold Council news
    news = ctx.get("news")
    if news:
        parts.append(f"<h2>{T['sec1b']}</h2>")
        li = "".join(
            f"<li><a href='{n.get('url','')}' target='_blank'>{n.get('title','')}</a></li>"
            for n in news)
        src = ctx.get("news_source", "")
        parts.append(f"<div class='card'><ul class='news'>{li}</ul>"
                     f"<div class='sub' style='margin-top:8px'>{T['src_label']}{src}</div></div>")

    # Backtest performance
    parts.append(f"<h2>{T['sec2']}</h2>")
    if m:
        kp = "".join(f"<div class='kpi'><div class='k'>{k}</div><div class='v'>{v}</div></div>"
                     for k, v in m.items())
        parts.append(f"<div class='card'><div class='kpis'>{kp}</div></div>")
    parts.append(svg_line(ctx.get("equity"), label=T["equity"], lang=lang))

    # Historical data analysis
    parts.append(f"<h2>{T['sec3']}</h2>")
    for key in ("season_month", "season_dow", "session", "conv", "attr", "fwd", "seg"):
        title = {"season_month": T["s31"], "season_dow": T["s32"], "session": T["s33"],
                 "conv": T["s34"], "attr": T["s35"], "fwd": T["s36"], "seg": T["s37"]}[key]
        d = ctx.get(key)
        if d is None or (hasattr(d, "empty") and d.empty):
            continue
        parts.append(f"<h3>{title}</h3><div class='card'>{df_html(d, lang=lang)}</div>")
    if ctx.get("season_month") is not None:
        try:
            parts.append(svg_bars(ctx["season_month"], "平均收益", label=T["month_ret"], lang=lang))
        except Exception:
            pass

    # Recent trades
    parts.append(f"<h2>{T['sec4']}</h2>")
    parts.append(f"<div class='card'>{df_html(ctx.get('recent_trades'), index=False, lang=lang)}</div>")

    # Current status & MT5 signal
    parts.append(f"<h2>{T['sec5']}</h2>")
    parts.append(f"<div class='card'>{df_html(ctx.get('current'), index=False, lang=lang)}</div>")
    if ctx.get("signal_ini"):
        parts.append(f"<h3>{T['ini_h']}</h3><pre>"
                     + ctx["signal_ini"].replace("<", "&lt;") + "</pre>")
    if ctx.get("warn"):
        parts.append(f"<div class='note'>{ctx['warn']}</div>")

    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{_CSS}</style></head>" \
           f"<body><div class='wrap'>{a}{''.join(parts)}</div></body></html>"


# ------------------------------------------------------- MT5 Export --------
def export_signal_ini(path: str, fund: Dict, levels: Dict, meta: Dict, lang: str = "zh") -> str:
    """Export key=value text readable by the MT5 EA (avoids parsing JSON inside the EA)."""
    # Driver factor details (name:score:weight, separated by |) for the MT5 panel's "fundamental view".
    _NAME_CN = {"geopolitics": "地缘政治", "growth": "经济增长", "real_rate": "利率水平",
                "capital_flow": "资本流动", "jewelry": "金饰需求", "industrial": "工业用金",
                "central_bank": "央行购金"}
    _NAME_EN = {"geopolitics": "Geo-politics", "growth": "Economic growth", "real_rate": "Real rate",
                "capital_flow": "Capital flows", "jewelry": "Jewelry demand", "industrial": "Industrial use",
                "central_bank": "CB buying"}
    _NAME = _NAME_EN if lang == "en" else _NAME_CN
    _facts = fund.get("parts", {}) or {}
    factors_line = "|".join(
        f"{_NAME.get(k, k)}:{float(v.get('score', 0)):+.2f}:{float(v.get('weight', 0)):.2f}"
        for k, v in _facts.items())
    lines = [
        _I18N.get(lang, _I18N["zh"])["ini1"],
        _I18N.get(lang, _I18N["zh"])["ini2"],
        f"updated={fund.get('asof','')}",
        f"score={fund.get('score',0.0)}",
        f"bias={fund.get('bias',0)}",
        f"bias_state={fund.get('bias_state','ok')}",
        f"coverage={fund.get('coverage',1.0):.2f}",
        f"data_note={fund.get('data_note','')}",
        f"factors={factors_line}",
        f"d1_trend={meta.get('d1_trend',0)}",
        f"regime={meta.get('regime','')}",
        f"size_mult={fund.get('size_mult',1.0)}",
        f"veto={1 if meta.get('veto', True) else 0}",
        f"kelly={meta.get('kelly',0.0)}",
        f"kelly_raw={meta.get('kelly_raw',0.0)}",
        f"atr={levels.get('atr',0.0)}",
        f"bb_up={levels.get('bb_up',0.0)}",
        f"bb_mid={levels.get('bb_mid',0.0)}",
        f"bb_lo={levels.get('bb_lo',0.0)}",
        f"guppy_state={levels.get('guppy_state',0)}",
        f"pivot_p={levels.get('pivot_p',0.0)}",
        f"pivot_r1={levels.get('pivot_r1',0.0)}",
        f"pivot_s1={levels.get('pivot_s1',0.0)}",
        f"fib_382={levels.get('fib_382',0.0)}",
        f"fib_618={levels.get('fib_618',0.0)}",
        f"last_price={levels.get('last_price',0.0)}",
    ]
    txt = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)
    return txt
