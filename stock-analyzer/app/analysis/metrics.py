"""Historical metrics. Pure functions: what goes in is all they can see.

`adj` is the dividend- and split-adjusted close. A missing value in the result
means there was not enough data, and scoring reports it as missing.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

DAYS_1Y = 252
DAYS_3Y = 756
DAYS_5Y = 1260
DAYS_10Y = 2520


def _return_over(values: np.ndarray, days: int) -> float | None:
    if len(values) <= days or values[-days - 1] <= 0:
        return None
    return float(values[-1] / values[-days - 1] - 1)


def _cagr(values: np.ndarray, days: int) -> float | None:
    if len(values) <= days or values[-days - 1] <= 0:
        return None
    return float((values[-1] / values[-days - 1]) ** (DAYS_1Y / days) - 1)


def _max_drawdown(values: np.ndarray) -> float | None:
    if len(values) < 2:
        return None
    return float((values / np.maximum.accumulate(values) - 1).min())


def _rsi(values: np.ndarray, period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = np.diff(values[-(period * 15):])
    alpha = 1 / period
    gain = max(changes[0], 0.0)
    loss = max(-changes[0], 0.0)
    for change in changes[1:]:
        gain = gain * (1 - alpha) + max(change, 0.0) * alpha
        loss = loss * (1 - alpha) + max(-change, 0.0) * alpha
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return float(100 - 100 / (1 + gain / loss))


def compute_price_metrics(
    adj: pd.Series,
    benchmark: pd.Series | None = None,
    risk_free_pct: float = 2.0,
) -> dict:
    """Metrics from a price series with a DatetimeIndex, ending at the analysis date."""
    adj = adj.dropna()
    values = adj.to_numpy(dtype=float)
    n = len(values)
    out: dict = {
        "n_days": n,
        "last_date": adj.index[-1].date() if n else None,
        "history_years": n / DAYS_1Y,
    }
    if n < 2 or (values <= 0).any():
        return out

    last = values[-1]
    if n >= 50:
        out["sma50"] = float(values[-50:].mean())
    if n >= 200:
        out["sma200"] = float(values[-200:].mean())
        out["price_vs_sma200"] = float(last / out["sma200"] - 1)
        out["sma50_vs_sma200"] = float(out["sma50"] / out["sma200"] - 1)
    if n > DAYS_1Y:
        slope = np.polyfit(np.arange(DAYS_1Y + 1), np.log(values[-DAYS_1Y - 1:]), 1)[0]
        out["slope_12m"] = float(math.exp(slope * DAYS_1Y) - 1)

    out["r3"] = _return_over(values, 63)
    out["r6"] = _return_over(values, 126)
    out["r12"] = _return_over(values, DAYS_1Y)
    out["rsi"] = _rsi(values)

    returns = np.diff(np.log(values))
    if n > DAYS_1Y:
        out["vol_1y"] = float(returns[-DAYS_1Y:].std(ddof=1) * math.sqrt(DAYS_1Y))
    out["max_dd_all"] = _max_drawdown(values)
    if n > DAYS_1Y:
        out["max_dd_5y"] = _max_drawdown(values[-DAYS_5Y:])
    out["drawdown_now"] = float(last / values.max() - 1)
    out["cagr_5y"] = _cagr(values, DAYS_5Y)
    out["cagr_10y"] = _cagr(values, DAYS_10Y)
    if n > DAYS_1Y:
        out["cagr_all"] = _cagr(values, n - 1)

    if n > DAYS_1Y:
        window = returns[-DAYS_3Y:]
        volatility = window.std(ddof=1) * math.sqrt(DAYS_1Y)
        annual = math.exp(window.mean() * DAYS_1Y) - 1
        if volatility > 0:
            out["sharpe_3y"] = float((annual - risk_free_pct / 100) / volatility)

    if benchmark is not None and not benchmark.empty:
        bench = benchmark.dropna()
        bench_values = bench.to_numpy(dtype=float)
        bench_r12 = _return_over(bench_values, DAYS_1Y)
        if out.get("r12") is not None and bench_r12 is not None:
            out["relative_12m"] = out["r12"] - bench_r12
        joined = pd.concat([adj.iloc[-DAYS_3Y - 1:], bench.iloc[-DAYS_3Y - 1:]], axis=1, join="inner").dropna()
        if len(joined) > 120:
            logged = np.diff(np.log(joined.to_numpy(dtype=float)), axis=0)
            variance = logged[:, 1].var(ddof=1)
            if variance > 0:
                out["beta_3y"] = float(np.cov(logged[:, 0], logged[:, 1], ddof=1)[0, 1] / variance)
    return out


def compute_dividend_metrics(close: pd.Series, dividends: pd.Series | None) -> dict:
    """Dividend yield and growth. `close` is the unadjusted price."""
    out: dict = {"pays_dividend": False}
    if dividends is None or dividends.empty or close.empty:
        return out
    close = close.dropna()
    as_of = close.index[-1]
    dividends = dividends[dividends.index <= as_of].sort_index()
    if dividends.empty:
        return out

    year_ago = as_of - pd.Timedelta(days=365)
    ttm = float(dividends[dividends.index > year_ago].sum())
    out["pays_dividend"] = ttm > 0
    out["ttm_dividend"] = ttm
    if ttm > 0 and close.iloc[-1] > 0:
        out["yield"] = ttm / float(close.iloc[-1])

    # Compare today's yield with its own month-end values over the past 5 years.
    start = as_of - pd.Timedelta(days=365 * 5)
    month_ends = close[close.index >= start].resample("ME").last().dropna()
    history = []
    for date, price in month_ends.items():
        trailing = dividends[(dividends.index > date - pd.Timedelta(days=365)) & (dividends.index <= date)].sum()
        if price > 0 and trailing > 0:
            history.append(float(trailing) / float(price))
    if len(history) >= 24 and out.get("yield") is not None:
        out["yield_percentile"] = float((np.array(history) < out["yield"]).mean() * 100)

    # Years in a row with higher dividends. The current, unfinished year doesn't count.
    yearly = dividends.groupby(dividends.index.year).sum()
    yearly = yearly[yearly.index < as_of.year]
    streak = 0
    values = yearly.to_numpy(dtype=float)
    for i in range(len(values) - 1, 0, -1):
        if values[i] > 0 and values[i] >= values[i - 1] and yearly.index[i] - yearly.index[i - 1] == 1:
            streak += 1
        else:
            break
    out["dividend_streak"] = streak
    return out
