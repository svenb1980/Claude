"""Replay the price-based rules through history, month by month.

Each signal is computed from data up to and including that month-end only, and earns
the return of the following month. The series are cut by position before scoring,
so later data cannot reach the calculation. A test verifies this by changing the future.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.analysis.metrics import compute_price_metrics
from app.analysis.scoring import score_price_only

MIN_HISTORY_DAYS = 252
LOOKBACK_DAYS = 1300  # Enough for all 5-year windows, and keeps a Pi fast.
MAX_STALE_DAYS = 10
MIN_STOCKS = 3


def _curve_stats(returns: list[float], months: int) -> dict:
    values = np.cumprod(1 + np.array(returns))
    peak = np.maximum.accumulate(np.concatenate([[1.0], values]))
    return {
        "total": float(values[-1] - 1),
        "cagr": float(values[-1] ** (12 / months) - 1) if values[-1] > 0 else -1.0,
        "max_dd": float((np.concatenate([[1.0], values]) / peak - 1).min()),
        "vol": float(np.std(returns, ddof=1) * math.sqrt(12)) if len(returns) > 1 else 0.0,
    }


def run_backtest(
    prices: dict[str, pd.Series],
    benchmark: pd.Series | None,
    analysis: dict,
    cost_pct: float = 0.1,
) -> dict | None:
    """`prices` holds adjusted closes per ticker. Returns None without enough data."""
    series = {t: s.dropna().sort_index() for t, s in prices.items() if len(s.dropna()) > MIN_HISTORY_DAYS}
    if not series:
        return None
    bench = benchmark.dropna().sort_index() if benchmark is not None and not benchmark.empty else None

    calendar = pd.DatetimeIndex(sorted(set().union(*(s.index for s in series.values()))))
    month_ends = pd.Series(calendar, index=calendar).groupby([calendar.year, calendar.month]).last()
    dates = list(pd.DatetimeIndex(month_ends.values))
    if len(dates) < 3:
        return None

    positions = {t: s.index.searchsorted(dates, side="right") for t, s in series.items()}
    bench_positions = bench.index.searchsorted(dates, side="right") if bench is not None else None

    def price_at(ticker: str, i: int) -> float | None:
        s = series[ticker]
        p = positions[ticker][i]
        if p == 0 or (dates[i] - s.index[p - 1]).days > MAX_STALE_DAYS:
            return None
        return float(s.iloc[p - 1])

    def bench_at(i: int) -> float | None:
        if bench is None or bench_positions[i] == 0:
            return None
        return float(bench.iloc[bench_positions[i] - 1])

    curve: list[dict] = []
    strategy_returns: list[float] = []
    hold_returns: list[float] = []
    bench_returns: list[float] = []
    signal_log: dict[str, dict[str, str]] = {}
    label_stats: dict[str, dict] = {
        key: {"count": 0, "r1": [], "r3": [], "beat": 0, "beat_n": 0} for key in ("sell", "hold", "buy")
    }
    previous_weights: dict[str, float] = {}
    levels = {"strategy": 100.0, "hold": 100.0, "benchmark": 100.0}
    # Comparing variants only means something over one shared period and with a real
    # spread of stocks, so the run waits for the benchmark and a minimum number of stocks.
    min_stocks = min(MIN_STOCKS, len(series))

    for i in range(len(dates) - 1):
        if bench is not None and bench_positions[i] == 0:
            continue
        bench_slice = None
        if bench is not None:
            start = max(0, bench_positions[i] - LOOKBACK_DAYS)
            bench_slice = bench.iloc[start : bench_positions[i]]

        labels: dict[str, str] = {}
        for ticker, s in series.items():
            p = positions[ticker][i]
            if p < MIN_HISTORY_DAYS or price_at(ticker, i) is None:
                continue
            window = s.iloc[max(0, p - LOOKBACK_DAYS) : p]
            metrics = compute_price_metrics(window, bench_slice, analysis["risk_free_pct"])
            labels[ticker] = score_price_only(metrics, analysis).label
        if len(labels) < min_stocks:
            continue
        signal_log[dates[i].date().isoformat()] = labels

        forward: dict[str, float] = {}
        for ticker in labels:
            now, later = price_at(ticker, i), price_at(ticker, i + 1)
            if now and later:
                forward[ticker] = later / now - 1
        if not forward:
            continue

        b_now, b_later = bench_at(i), bench_at(i + 1)
        bench_r = b_later / b_now - 1 if b_now and b_later else None

        for ticker, label in labels.items():
            if label not in label_stats or ticker not in forward:
                continue
            stats = label_stats[label]
            stats["count"] += 1
            stats["r1"].append(forward[ticker])
            if bench_r is not None:
                stats["beat_n"] += 1
                stats["beat"] += int(forward[ticker] > bench_r)
            if i + 3 < len(dates):
                now, later = price_at(ticker, i), price_at(ticker, i + 3)
                if now and later:
                    stats["r3"].append(later / now - 1)

        kept = [t for t in forward if labels[t] in ("hold", "buy")]
        weights = {t: 1 / len(kept) for t in kept}
        turnover = sum(abs(weights.get(t, 0.0) - previous_weights.get(t, 0.0)) for t in set(weights) | set(previous_weights))
        previous_weights = weights

        strategy_r = sum(weights[t] * forward[t] for t in kept) - turnover * cost_pct / 100
        hold_r = float(np.mean(list(forward.values())))
        strategy_returns.append(strategy_r)
        hold_returns.append(hold_r)
        if not curve:
            curve.append({
                "date": dates[i].date().isoformat(), "strategy": 100.0, "hold": 100.0,
                "benchmark": 100.0 if bench_r is not None else None,
            })
        levels["strategy"] *= 1 + strategy_r
        levels["hold"] *= 1 + hold_r
        if bench_r is not None:
            bench_returns.append(bench_r)
            levels["benchmark"] *= 1 + bench_r
        curve.append({
            "date": dates[i + 1].date().isoformat(),
            "strategy": levels["strategy"],
            "hold": levels["hold"],
            "benchmark": levels["benchmark"] if bench_returns else None,
        })

    if not strategy_returns:
        return None
    months = len(strategy_returns)
    labels_summary = {}
    for key, stats in label_stats.items():
        labels_summary[key] = {
            "count": stats["count"],
            "avg_1m": float(np.mean(stats["r1"])) if stats["r1"] else None,
            "avg_3m": float(np.mean(stats["r3"])) if stats["r3"] else None,
            "hit_rate": stats["beat"] / stats["beat_n"] if stats["beat_n"] else None,
        }
    return {
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
        "months": months,
        "tickers": len(series),
        "cost_pct": cost_pct,
        "curve": curve,
        "stats": {
            "strategy": _curve_stats(strategy_returns, months),
            "hold": _curve_stats(hold_returns, months),
            "benchmark": _curve_stats(bench_returns, len(bench_returns)) if bench_returns else None,
        },
        "labels": labels_summary,
        "signals": signal_log,
    }
