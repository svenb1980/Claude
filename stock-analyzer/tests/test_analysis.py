from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from app.analysis.backtest import run_backtest
from app.analysis.metrics import compute_dividend_metrics, compute_price_metrics
from app.analysis.scoring import score_holding, score_price_only
from app.settings_store import DEFAULT_ANALYSIS
from tests.conftest import synthetic_prices

ANALYSIS = deepcopy(DEFAULT_ANALYSIS)
CTX = {"weight_pct": 5.0, "sector": "Technology", "sector_pct": 20.0, "currency": "EUR", "currency_pct": 100.0}
FUND = {"trailing_pe": 15.0, "payout_ratio": 0.4, "profit_margin": 0.2, "debt_to_equity": 50.0}


def series(values, end="2026-11-03"):
    return pd.Series(np.array(values, dtype=float), index=pd.bdate_range(end=end, periods=len(values)))


def test_returns_against_hand_calculation():
    # A constant 0.1% per day, so every result can be calculated exactly.
    values = 100 * 1.001 ** np.arange(1301)
    m = compute_price_metrics(series(values))
    assert m["r3"] == pytest.approx(1.001**63 - 1)
    assert m["r12"] == pytest.approx(1.001**252 - 1)
    assert m["cagr_5y"] == pytest.approx(1.001**252 - 1)
    assert m["slope_12m"] == pytest.approx(1.001**252 - 1)
    assert m["vol_1y"] == pytest.approx(0, abs=1e-9)
    assert m["max_dd_all"] == 0


def test_moving_averages_and_drawdown():
    values = list(range(1, 301))
    m = compute_price_metrics(series(values))
    assert m["sma50"] == pytest.approx(np.mean(values[-50:]))
    assert m["sma200"] == pytest.approx(np.mean(values[-200:]))
    m = compute_price_metrics(series([100, 50, 75]))
    assert m["max_dd_all"] == pytest.approx(-0.5)
    assert m["drawdown_now"] == pytest.approx(-0.25)


def test_rsi_extremes():
    assert compute_price_metrics(series(range(1, 60)))["rsi"] == 100
    assert compute_price_metrics(series(range(60, 1, -1)))["rsi"] < 1


def test_beta_of_a_doubled_move_is_two():
    rng = np.random.default_rng(5)
    bench_r = rng.normal(0, 0.01, 800)
    bench = series(100 * np.exp(np.cumsum(bench_r)))
    stock = series(100 * np.exp(np.cumsum(2 * bench_r)))
    assert compute_price_metrics(stock, bench)["beta_3y"] == pytest.approx(2, abs=1e-9)


def test_short_history_gives_missing_not_invented_values():
    m = compute_price_metrics(series(range(1, 30)))
    assert "sma200" not in m and "vol_1y" not in m and m["r12"] is None


def test_dividend_metrics():
    close = series([100.0] * 600)
    last = close.index[-1]
    dates = pd.to_datetime([f"{y}-03-01" for y in range(2021, 2027)])
    dividends = pd.Series([1.0, 1.1, 1.2, 1.3, 1.3, 2.0], index=dates)
    m = compute_dividend_metrics(close, dividends)
    assert m["pays_dividend"] is True
    assert m["yield"] == pytest.approx(0.02)
    assert m["dividend_streak"] == 4  # 2022-2025; the unfinished 2026 doesn't count
    assert compute_dividend_metrics(close, dividends[dividends.index > last])["pays_dividend"] is False


def test_dividend_metrics_ignore_future_dividends():
    close = series([100.0] * 300, end="2024-06-28")
    dividends = pd.Series([1.0, 50.0], index=pd.to_datetime(["2024-03-01", "2025-03-01"]))
    assert compute_dividend_metrics(close, dividends)["ttm_dividend"] == 1.0


def _metrics(drift, seed=1):
    return compute_price_metrics(synthetic_prices(drift=drift, vol=0.008, seed=seed))


def test_strong_uptrend_scores_higher_than_downtrend():
    up = score_holding({**_metrics(0.0015), "pays_dividend": False}, FUND, CTX, ANALYSIS, "EQUITY")
    down = score_holding({**_metrics(-0.0015), "pays_dividend": False}, FUND, CTX, ANALYSIS, "EQUITY")
    assert up.total > down.total
    assert up.label in ("buy", "hold")
    assert down.label in ("sell", "hold")


def test_labels_follow_thresholds():
    metrics = {**_metrics(0.0005), "pays_dividend": False}
    base = score_holding(metrics, FUND, CTX, ANALYSIS, "EQUITY")
    assert score_holding(metrics, FUND, CTX, {**ANALYSIS, "buy_from": base.total - 1, "sell_below": 0}, "EQUITY").label == "buy"
    assert score_holding(metrics, FUND, CTX, {**ANALYSIS, "sell_below": base.total + 1, "buy_from": 100}, "EQUITY").label == "sell"


def test_missing_data_lowers_confidence_and_is_not_scored_neutral():
    full = score_holding({**_metrics(0.001), "pays_dividend": False}, FUND, CTX, ANALYSIS, "EQUITY")
    assert full.confidence == pytest.approx(100, abs=15)
    empty = score_holding({}, {}, {"weight_pct": None}, ANALYSIS, "EQUITY")
    assert empty.label == "insufficient"
    assert empty.total is None
    assert empty.confidence == 0
    valuation = next(f for f in empty.factors if f.key == "valuation")
    assert valuation.score is None and valuation.missing


def test_position_over_the_limit_never_gets_buy():
    metrics = {**_metrics(0.0005), "pays_dividend": False}
    settings = {**ANALYSIS, "buy_from": 1.0, "sell_below": 0.0}
    assert score_holding(metrics, FUND, CTX, settings, "EQUITY").label == "buy"
    capped = score_holding(metrics, FUND, {**CTX, "weight_pct": 30.0}, settings, "EQUITY")
    assert capped.label == "hold"
    assert "geblokkeerd" in capped.notes[0]


def test_etf_skips_company_factors_without_losing_confidence():
    result = score_holding({**_metrics(0.0005), "pays_dividend": False}, {}, CTX, ANALYSIS, "ETF")
    assert result.confidence > 80
    assert not next(f for f in result.factors if f.key == "quality").applicable


def test_reasons_show_actual_numbers():
    metrics = {"price_vs_sma200": -0.12}
    result = score_price_only(metrics, ANALYSIS)
    text = result.factors[0].reasons[0][1]
    assert "-12,0%" in text and "200-daags" in text


def test_backtest_uses_no_future_data():
    a = synthetic_prices(seed=10, days=1000)
    b = synthetic_prices(seed=11, days=1000)
    bench = synthetic_prices(seed=12, days=1000)
    base = run_backtest({"A": a, "B": b}, bench, ANALYSIS)

    cut = a.index[700]
    changed_a = a.copy()
    changed_a[changed_a.index > cut] *= 5  # The future changes completely.
    changed_bench = bench.copy()
    changed_bench[changed_bench.index > cut] *= 0.2
    changed = run_backtest({"A": changed_a, "B": b}, changed_bench, ANALYSIS)

    earlier = [d for d in base["signals"] if pd.Timestamp(d) <= cut]
    assert len(earlier) > 10
    for date in earlier:
        assert base["signals"][date] == changed["signals"][date], date
    later = [d for d in base["signals"] if pd.Timestamp(d) > cut]
    assert any(base["signals"][d] != changed["signals"][d] for d in later)


def test_backtest_transaction_costs_reduce_return():
    prices = {"A": synthetic_prices(seed=20, days=900, vol=0.03), "B": synthetic_prices(seed=21, days=900, vol=0.03)}
    free = run_backtest(prices, None, ANALYSIS, cost_pct=0.0)
    costly = run_backtest(prices, None, ANALYSIS, cost_pct=1.0)
    assert costly["stats"]["strategy"]["total"] < free["stats"]["strategy"]["total"]
    assert costly["stats"]["hold"]["total"] == pytest.approx(free["stats"]["hold"]["total"])


def test_backtest_compares_all_variants_over_the_same_period():
    # One old stock and a much younger benchmark, as with Microsoft against an ETF from 2009.
    old = synthetic_prices(seed=30, days=3000)
    young_a = synthetic_prices(seed=31, days=1000)
    young_b = synthetic_prices(seed=32, days=1000)
    bench = synthetic_prices(seed=33, days=800)
    result = run_backtest({"OLD": old, "A": young_a, "B": young_b}, bench, ANALYSIS)
    assert pd.Timestamp(result["start"]) >= bench.index[0]
    assert all(point["benchmark"] is not None for point in result["curve"])
    assert result["curve"][0]["benchmark"] == 100.0
    assert len(result["curve"]) == result["months"] + 1


def test_backtest_waits_for_a_spread_of_stocks():
    old = synthetic_prices(seed=30, days=3000)
    young_a = synthetic_prices(seed=31, days=1000)
    young_b = synthetic_prices(seed=32, days=1000)
    result = run_backtest({"OLD": old, "A": young_a, "B": young_b}, None, ANALYSIS)
    assert pd.Timestamp(result["start"]) >= young_a.index[0]


def test_backtest_without_enough_data_returns_none():
    assert run_backtest({"A": synthetic_prices(days=100)}, None, ANALYSIS) is None
    assert run_backtest({}, None, ANALYSIS) is None
