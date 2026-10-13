"""Scrape data from the World Gold Council (gold.org).

Value: WGC publishes the quarterly "Gold Demand Trends", which includes the gold
supply/demand balance sheet (by sector, with 5 quarters of history). This table
maps directly onto the four factors in the driver analysis:

    Central bank buying  -> Central Banks & Other inst.   (weight 1.5, previously had to be entered by hand)
    Capital flows        -> ETFs & Similar Products        (weight 1.5, previously relied on GLD momentum, often unavailable)
    Jewellery demand     -> Jewellery Consumption          (weight 0.8, previously only a seasonal proxy)
    Industrial gold      -> Technology                     (weight 0.5, previously only an INDPRO proxy)

Site notes:
  - A User-Agent header is required, otherwise 403.
  - Responses are gzip-compressed; urllib must decompress manually (curl on this machine does not support --compressed).
  - /rss.xml is useless (only 10 items, mostly site cruft) — do not use it.
  - The research library page is server-rendered, so links can be extracted directly with regex.
"""
from __future__ import annotations

import gzip
import re
import urllib.request
from typing import Dict, List, Optional, Tuple

import pandas as pd

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip",
}

BASE = "https://www.gold.org"
LIBRARY = BASE + "/goldhub/research/library"

# table name -> internal key
_ROW_MAP = {
    "central bank": "central_bank",
    "etf": "etf",
    "jewellery consumption": "jewelry",
    "technology": "technology",
    "total bar and coin": "bar_coin",
    "total demand": "total_demand",
    "total supply": "total_supply",
    "lbma gold price": "price",
}


def _get(url: str, timeout: int = 25) -> Optional[str]:
    """GET text, auto-decompress gzip. Returns None on failure."""
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if "gzip" in (r.headers.get("Content-Encoding") or ""):
                raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")
    except Exception:
        return None


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#039;", "'")
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------
# Gold Demand Trends
# --------------------------------------------------------------------------
def latest_gdt_url(timeout: int = 25) -> Optional[str]:
    """Find the URL of the latest Gold Demand Trends issue from the research library page."""
    html = _get(LIBRARY, timeout)
    if not html:
        return None
    found = set(re.findall(
        r'href="(/goldhub/research/gold-demand-trends/gold-demand-trends-[^"]+)"', html))
    if not found:
        return None

    # Exclude regional editions (US / India / China Focus etc.) — their tables use a different scope and are not the global supply/demand table
    glob = [u for u in found if "focus" not in u.lower()]
    cands = glob or list(found)

    def _key(u: str) -> Tuple[int, int]:
        m = re.search(r"q([1-4])-(\d{4})", u)
        return (int(m.group(2)), int(m.group(1))) if m else (0, 0)

    return BASE + sorted(cands, key=_key)[-1]


def fetch_gdt(url: Optional[str] = None, timeout: int = 25) -> Optional[Dict]:
    """Parse the Gold Demand Trends supply/demand balance sheet.

    Returns {"quarter": "Q2'26", "url": ..., "table": {key: [5 quarter values]},
             "latest": {key: latest value}, "yoy": {key: YoY %}, ...}
    Units: tonnes (LBMA price in US$/oz). The last column is the latest quarter.
    """
    if url is None:
        url = latest_gdt_url(timeout)
    if not url:
        return None
    html = _get(url, timeout)
    if not html:
        return None

    # Locate the supply/demand table
    table_html = None
    for m in re.finditer(r"<table[^>]*>", html):
        seg = html[m.start():m.start() + 8000]
        if "Mine Production" in seg and "Central Bank" in seg:
            table_html = seg
            break
    if not table_html:
        return None

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S)
    header: List[str] = []
    table: Dict[str, List[float]] = {}
    for r in rows:
        cells = [_strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        cells = [c for c in cells if c]
        if not cells:
            continue
        # Header row: contains >=2 quarter columns like "Q2'25"
        qcols = [c for c in cells if re.match(r"^Q\d'\d\d$", c)]
        if len(qcols) >= 2 and not header:
            header = qcols
            continue
        # Fallback: re-detect quarter columns if header not yet found (e.g. first cell &nbsp; stripped)
        if not header and len(qcols) == 1 and len(cells) >= 5:
            header = qcols
            continue

        name = cells[0].lower().strip()
        key = next((v for k, v in _ROW_MAP.items() if k in name), None)
        if key is None:
            continue
        vals: List[float] = []
        for c in cells[1:]:
            c = c.replace(",", "")
            m = re.match(r"^-?\d+(?:\.\d+)?$", c)
            if m:
                vals.append(float(c))
            else:
                break
        if len(vals) >= 5:
            table[key] = vals[:len(header)] if header else vals[:5]

    if not table:
        return None

    n = len(header) if header else 5
    latest = {k: v[-1] for k, v in table.items()}
    prev_q = {k: v[-2] for k, v in table.items() if len(v) >= 2}
    year_ago = {k: v[-5] for k, v in table.items() if len(v) >= 5}

    def _pct(cur: Optional[float], base: Optional[float]) -> Optional[float]:
        if cur is None or base is None or base == 0:
            return None
        return (cur / abs(base) - 1.0) * 100.0

    yoy = {k: _pct(latest.get(k), year_ago.get(k)) for k in latest}
    qoq = {k: _pct(latest.get(k), prev_q.get(k)) for k in latest}

    return {
        "url": url,
        "quarters": header or [f"T-{i}" for i in range(n - 1, -1, -1)],
        "quarter": (header[-1] if header else "?"),
        "table": table,
        "latest": latest,
        "prev_q": prev_q,
        "year_ago": year_ago,
        "yoy": yoy,
        "qoq": qoq,
    }


# --------------------------------------------------------------------------
# Research news
# --------------------------------------------------------------------------
def fetch_news(limit: int = 10, timeout: int = 25) -> List[Dict[str, str]]:
    """Featured articles from the research library homepage (title + link)."""
    html = _get(LIBRARY, timeout)
    if not html:
        return []
    out: List[Dict[str, str]] = []
    seen = set()
    for m in re.finditer(
            r'<a href="(/goldhub/research/[^"]+)">.*?<h3[^>]*>\s*([^<]{8,160}?)\s*</h3>',
            html, re.S):
        url, title = m.group(1), _strip_tags(m.group(2))
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": title, "url": BASE + url})
        if len(out) >= limit:
            break
    return out
