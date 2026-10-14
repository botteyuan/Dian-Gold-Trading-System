#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a self-contained SVG equity curve from backtest_full_equity.csv."""
import csv, math, datetime as dt

SRC = "output/backtest_full_equity.csv"
OUT = "output/equity_curve.html"

rows = []
with open(SRC, encoding="utf-8-sig") as f:
    for r in csv.reader(f):
        if not r or r[0].startswith("#"):
            continue
        try:
            d = dt.datetime.strptime(r[0].strip(), "%Y-%m-%d").timestamp()
            e = float(r[1])
        except Exception:
            continue
        rows.append((d, e))

rows.sort()
xs = [r[0] for r in rows]
ys = [r[1] for r in rows]

# drawdown series
peak = ys[0]
dd = []
for e in ys:
    peak = max(peak, e)
    dd.append(e / peak - 1.0)

xmin, xmax = xs[0], xs[-1]
ymin, ymax = min(ys), max(ys)
ddmin = min(dd)

# layout
W = 960
PAD_L, PAD_R = 70, 24
TOP_H = 380
DD_H = 130
GAP = 28
PAD_T = 70
PAD_B = 46
eq_top = PAD_T
eq_bot = PAD_T + TOP_H
dd_top = eq_bot + GAP
dd_bot = dd_top + DD_H
H = dd_bot + PAD_B

def sx(x):
    return PAD_L + (x - xmin) / (xmax - xmin) * (W - PAD_L - PAD_R)

def sy_eq(y):
    return eq_bot - (y - ymin) / (ymax - ymin) * (eq_bot - eq_top)

def sy_dd(v):  # v in [-1,0]
    return dd_top + (-v) / (-ddmin) * (dd_bot - dd_top)

# equity polyline
eq_pts = " ".join(f"{sx(x):.1f},{sy_eq(y):.1f}" for x, y in zip(xs, ys))
# drawdown area (clamp 0 baseline)
dd_area = f"{sx(xs[0]):.1f},{dd_top:.1f} "
dd_area += " ".join(f"{sx(x):.1f},{sy_dd(v):.1f}" for x, v in zip(xs, dd))
dd_area += f" {sx(xs[-1]):.1f},{dd_top:.1f}"

# year gridlines
years = list(range(2021, 2027))
xticks = []
for y in years:
    try:
        ts = dt.datetime(y, 1, 1).timestamp()
        if xmin <= ts <= xmax:
            xticks.append((ts, str(y)))
    except Exception:
        pass

# y gridlines (equity)
eq_yticks = []
lo = math.floor(ymin / 5000) * 5000
hi = math.ceil(ymax / 5000) * 5000
v = lo
while v <= hi:
    eq_yticks.append(v)
    v += 5000

# dd y ticks
dd_yticks = [0.0]
step = -0.1
tv = step
while tv >= ddmin - 1e-9:
    dd_yticks.append(tv)
    tv += step

# find max drawdown point
mdd_i = dd.index(ddmin)
mdd_x, mdd_y = xs[mdd_i], ys[mdd_i]

CN_RED = "#c0392b"   # 涨
CN_GREEN = "#1e8e3e" # 跌

def fmt_eq(v):
    return f"${v:,.0f}"

grid = "#e6e8eb"
txt = "#555"
txt_dark = "#222"
small = 12

svg = []
svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Consolas,Segoe UI,Microsoft YaHei,sans-serif">')

# title
svg.append(f'<text x="{W/2:.0f}" y="30" text-anchor="middle" font-size="20" font-weight="700" fill="{txt_dark}">帝娜黄金系统 · 收益曲线</text>')
svg.append(f'<text x="{W/2:.0f}" y="52" text-anchor="middle" font-size="13" fill="{txt}">ATR 风险 2.0% · 初始 $10,000 · B3 生产口径 · 2021-01 ~ 2026-09（{len(rows)} 交易日）</text>')

# ---- equity panel frame ----
svg.append(f'<rect x="{PAD_L}" y="{eq_top}" width="{W-PAD_L-PAD_R}" height="{TOP_H}" fill="#fcfcfd" stroke="{grid}"/>')
# equity y grid + labels
for v in eq_yticks:
    yy = sy_eq(v)
    svg.append(f'<line x1="{PAD_L}" y1="{yy:.1f}" x2="{W-PAD_R}" y2="{yy:.1f}" stroke="{grid}" stroke-width="1"/>')
    svg.append(f'<text x="{PAD_L-8:.0f}" y="{yy+4:.1f}" text-anchor="end" font-size="{small}" fill="{txt}">{fmt_eq(v)}</text>')

# x grid (years)
for ts, lab in xticks:
    xx = sx(ts)
    svg.append(f'<line x1="{xx:.1f}" y1="{eq_top}" x2="{xx:.1f}" y2="{dd_bot}" stroke="{grid}" stroke-width="1" stroke-dasharray="3 3"/>')
    svg.append(f'<text x="{xx:.1f}" y="{dd_bot+20:.1f}" text-anchor="middle" font-size="{small}" fill="{txt}">{lab}</text>')

# equity area fill (subtle) + line
eq_area = f"{sx(xs[0]):.1f},{eq_bot:.1f} " + " ".join(f"{sx(x):.1f},{sy_eq(y):.1f}" for x, y in zip(xs, ys)) + f" {sx(xs[-1]):.1f},{eq_bot:.1f}"
svg.append(f'<polygon points="{eq_area}" fill="{CN_RED}" fill-opacity="0.06"/>')
svg.append(f'<polyline points="{eq_pts}" fill="none" stroke="{CN_RED}" stroke-width="1.8"/>')

# start / end markers
svg.append(f'<circle cx="{sx(xs[0]):.1f}" cy="{sy_eq(ys[0]):.1f}" r="3.5" fill="{CN_RED}"/>')
svg.append(f'<circle cx="{sx(xs[-1]):.1f}" cy="{sy_eq(ys[-1]):.1f}" r="3.5" fill="{CN_RED}"/>')
svg.append(f'<text x="{sx(xs[-1]):.1f}" y="{sy_eq(ys[-1])-12:.1f}" text-anchor="end" font-size="13" font-weight="700" fill="{CN_RED}">终 ${ys[-1]:,.0f}</text>')
svg.append(f'<text x="{sx(xs[0]):.1f}" y="{sy_eq(ys[0])+18:.1f}" text-anchor="start" font-size="12" fill="{txt}">起 $10,000</text>')

# ---- drawdown panel ----
svg.append(f'<rect x="{PAD_L}" y="{dd_top}" width="{W-PAD_L-PAD_R}" height="{DD_H}" fill="#fcfcfd" stroke="{grid}"/>')
for v in dd_yticks:
    yy = sy_dd(v)
    svg.append(f'<line x1="{PAD_L}" y1="{yy:.1f}" x2="{W-PAD_R}" y2="{yy:.1f}" stroke="{grid}" stroke-width="1"/>')
    svg.append(f'<text x="{PAD_L-8:.0f}" y="{yy+4:.1f}" text-anchor="end" font-size="{small}" fill="{txt}">{v*100:.0f}%</text>')
# baseline 0
svg.append(f'<line x1="{PAD_L}" y1="{dd_top}" x2="{W-PAD_R}" y2="{dd_top}" stroke="{txt}" stroke-width="1.2"/>')
svg.append(f'<polygon points="{dd_area}" fill="{CN_GREEN}" fill-opacity="0.30" stroke="{CN_GREEN}" stroke-width="1"/>')
# max dd marker
svg.append(f'<circle cx="{sx(mdd_x):.1f}" cy="{sy_dd(ddmin):.1f}" r="3.5" fill="{CN_GREEN}"/>')
svg.append(f'<text x="{sx(mdd_x):.1f}" y="{sy_dd(ddmin)+16:.1f}" text-anchor="middle" font-size="11" fill="{CN_GREEN}">最大回撤 {ddmin*100:.1f}%</text>')
svg.append(f'<text x="{PAD_L+4:.0f}" y="{dd_top-8:.1f}" font-size="12" fill="{txt}">回撤（水下）</text>')

# ---- stats chips ----
chips = [
    ("最终权益", f"${ys[-1]:,.0f}", CN_RED),
    ("总收益率", f"+{(ys[-1]/ys[0]-1)*100:.1f}%", CN_RED),
    ("最大回撤", f"{ddmin*100:.1f}%", CN_GREEN),
    ("夏普", "0.72", "#2d6cdf"),
    ("盈利因子", "1.22", "#2d6cdf"),
    ("交易笔数", "864", txt_dark),
]
cx = PAD_L
cy = H - 22
for i, (k, val, col) in enumerate(chips):
    svg.append(f'<rect x="{cx:.0f}" y="{cy-16:.0f}" width="140" height="26" rx="6" fill="#f4f6f8" stroke="{grid}"/>')
    svg.append(f'<text x="{cx+10:.0f}" y="{cy+2:.0f}" font-size="12" fill="{txt}">{k}</text>')
    svg.append(f'<text x="{cx+130:.0f}" y="{cy+2:.0f}" text-anchor="end" font-size="13" font-weight="700" fill="{col}">{val}</text>')
    cx += 148

svg.append('</svg>')

html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>帝娜黄金系统 · 收益曲线</title>
<style>body{{margin:0;background:#fff;display:flex;justify-content:center;padding:24px;font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif}}
.card{{box-shadow:0 4px 20px rgba(0,0,0,.08);border-radius:14px;overflow:hidden;background:#fff}}svg{{display:block;max-width:100%;height:auto}}</style>
</head><body><div class="card">{"".join(svg)}</div></body></html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print("written", OUT, "rows", len(rows), "final", ys[-1], "mdd", ddmin)
