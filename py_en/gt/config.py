"""Config loading (YAML -> dict with defaults)."""
from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Dict

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CONFIG = os.path.join(_ROOT, "config", "config.yaml")

_DEFAULTS: Dict[str, Any] = {
    "symbol": "XAUUSD",
    "bollinger": {"period": 13, "deviation": 1.618, "squeeze_lookback": 120,
                  "squeeze_percentile": 0.25, "expand_bars": 2},
    "guppy": {"short": [3, 5, 8, 10, 12, 15], "long": [30, 35, 40, 45, 50, 60],
              "pullback_atr_ratio": 0.60, "pullback_valid_bars": 60},
    "stochastic": {"k_period": 5, "d_period": 3, "slowing": 3,
                   "overbought": 80, "oversold": 20},
    "fibonacci": {"retracements": [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0],
                  "extensions": [1.272, 1.618, 2.618],
                  "swing_left": 5, "swing_right": 5, "swing_lookback": 200},
    "pivot": {"enabled": True, "method": "classic"},
    "candle": {"body_lookback": 20, "small_body_ratio": 0.60,
               "shadow_multiple": 1.5, "doji_body_range_ratio": 0.10},
    "entry": {"min_score": 3, "require_pullback": True, "trend_filter": False,
              "trend_ema": 50, "allow_long": True, "allow_short": False,
              "require_h4_resonance": False,
              "regime_enabled": True, "regime_skew_factor": 0.40,
              "regime_neutral_long_only": True, "regime_neutral_flat_aside": True},
    "h4": {"enabled": True, "band_touch_atr": 0.50, "engulfing_body_ratio": 1.0},
    "exit": {"atr_period": 14, "big_move_atr": 2.0, "close_beyond_outer": True,
             "close_beyond_middle": False, "stop_buffer_atr": 0.30,
             "initial_stop_atr": 1.2, "initial_stop_min_atr": 3.0,
             "max_hold_bars": 24,
             "trailing": {"enabled": True, "method": "atr",
                          "atr_multiple": 2.0, "activate_atr": 2.5},
             "reverse_signal_close": True},
    "risk": {"account_risk_pct": 1.0, "kelly_enabled": True, "kelly_cap": 0.03,
             "kelly_safety": 0.5, "max_lots": 5.0, "min_lots": 0.01},
    "fundamental": {
        "weights": {"geopolitics": 2.0, "growth": 1.0, "real_rate": 2.5,
                    "capital_flow": 1.5, "jewelry": 0.8, "industrial": 0.5},
        "bias_threshold": 2.0, "veto_enabled": False,
        "manual": {"central_bank_buying": 0.0, "jewelry_demand": 0.0,
                   "industrial_demand": 0.0},
    },
    "data": {"source": "auto", "bars": 20000, "cache_dir": "data/cache",
             "csv_path": "data/XAUUSD_H1.csv"},
    "backtest": {"initial_capital": 100000, "spread_points": 30,
                 "commission_per_lot": 0.0, "point_value": 100,
                 "start": "2022-01-01", "end": None},
    "output": {"dir": "output", "signal_file": "gold_signal.ini",
               "report_file": "report.html"},
}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> Dict[str, Any]:
    path = path or DEFAULT_CONFIG
    if yaml is None:
        raise RuntimeError("requires pyyaml: pip install pyyaml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    else:
        user = {}
    return _merge(_DEFAULTS, user)


def project_root() -> str:
    return _ROOT
