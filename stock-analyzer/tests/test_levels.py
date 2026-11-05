from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis.levels import (
    _ceiling_evidence,
    _floor_pivots,
    _stop_evidence,
    average_true_range,
    break_even_move_pct,
    chandelier_series,
    daily_levels,
    intraday_levels,
    prepare_ohlc,
    split_sessions,
    swing_highs,
)


def frame(close, spread=1.0, end="2026-11-03"):
    close = np.array(close, dtype=float)
    return pd.DataFrame(
        {"close": close, "adj_close": close, "volume": 1000.0, "high": close + spread, "low": close - spread},
        index=pd.bdate_range(end=end, periods=len(close)),
    )


def walk(days=1500, seed=4, drift=0.0003, vol=0.012):
    rng = np.random.default_rng(seed)
    return frame(100 * np.exp(np.cumsum(rng.normal(drift, vol, days))), spread=0.8)


def test_atr_against_hand_calculation():
    high = np.array([11.0, 12, 13, 14])
    low = np.array([9.0, 10, 11, 12])
    close = np.array([10.0, 11, 12, 13])
    atr = average_true_range(high, low, close, period=2)
    # True ranges: 2, 2, 2, 2.
    assert np.isnan(atr[0])
    assert atr[1:] == pytest.approx([2, 2, 2])


def test_chandelier_is_high_minus_three_atr():
    data = frame([100.0] * 40, spread=1.0)
    line = chandelier_series(prepare_ohlc(data))
    assert line.iloc[-1] == pytest.approx(101 - 3 * 2)


def test_levels_missing_highs_fall_back_to_close():
    data = frame([100.0] * 40)
    data["high"] = None
    data["low"] = None
    data[["high", "low"]] = data[["high", "low"]].apply(pd.to_numeric, errors="coerce")
    prepared = prepare_ohlc(data)
    assert (prepared["high"] == 100).all()


def test_stop_has_no_future_data():
    data = prepare_ohlc(walk())
    full = chandelier_series(data)
    cut = 900
    partial = chandelier_series(data.iloc[:cut])
    pd.testing.assert_series_equal(full.iloc[:cut], partial)


def test_stop_evidence_counts_crossings_and_compares_with_normal():
    close = [100.0] * 60 + [80.0] + [70.0] * 40
    data = prepare_ohlc(frame(close, spread=0.5))
    line = chandelier_series(data)
    evidence = _stop_evidence(data, line)
    assert evidence.events == 1
    assert evidence.avg_forward == pytest.approx(70 / 80 - 1)
    assert evidence.pct_lower == 1.0
    assert evidence.baseline is not None


def test_ceiling_evidence_counts_rejection_and_breakout():
    # Rises to 110 and falls back to 95 (held), then later breaks through to 130.
    close = [100.0] * 10 + [110.0] + [95.0] * 30 + [111.0] + [130.0] * 30
    data = prepare_ohlc(frame(close, spread=0.1))
    evidence = _ceiling_evidence(data, 110.0, atr=2.0)
    assert evidence.events == 2
    assert evidence.held == 1


def test_swing_highs_finds_peaks():
    close = [10, 11, 12, 13, 14, 15, 14, 13, 12, 11, 10, 11, 12, 13, 14, 13, 12, 11, 10, 9, 8]
    assert swing_highs(frame(close, spread=0), window=3) == [15.0, 14.0]


def test_daily_levels_are_sensible():
    result = daily_levels(walk())
    price = result["price"]
    assert result["levels"]
    stop = next(lv for lv in result["levels"] if lv.key == "stop")
    assert stop.price < price
    assert stop.distance_pct < 0
    for level in result["levels"]:
        if level.key != "stop":
            assert level.price > price
    assert [lv.price for lv in result["levels"]] == sorted((lv.price for lv in result["levels"]), reverse=True)


def test_stop_already_broken_says_so_and_verdict_compares_with_normal():
    from app.web.levels_view import daily_rows

    # A long rise, then a sharp fall that ends below the stop line.
    close = list(np.linspace(100, 200, 300)) + [120.0] * 3
    rows = daily_rows(daily_levels(frame(close, spread=0.5)))
    stop = next(row for row in rows if row["key"] == "stop")
    assert stop["distance_pct"] > 0
    assert "al onder deze stop" in stop["evidence"]


def test_verdict_wording():
    from app.analysis.levels import Evidence
    from app.web.levels_view import _verdict

    assert "geen duidelijk verschil" in _verdict(Evidence(pct_lower=0.46, baseline_lower=0.46))
    assert "vaker lager" in _verdict(Evidence(pct_lower=0.70, baseline_lower=0.46))
    assert "vaker hoger" in _verdict(Evidence(pct_lower=0.30, baseline_lower=0.46))
    assert _verdict(Evidence()) == ""


def test_daily_levels_need_enough_history():
    assert daily_levels(frame([100.0] * 10)) == {}


def bars(days=6, per_day=78, start="2026-10-26"):
    index, values = [], []
    for offset, day in enumerate(pd.bdate_range(start, periods=days)):
        session = pd.date_range(day + pd.Timedelta(hours=9), periods=per_day, freq="5min", tz="Europe/Amsterdam")
        index.extend(session)
        values.extend(100 + offset + np.sin(np.linspace(0, 6, per_day)))
    close = np.array(values)
    return pd.DataFrame({"open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 10.0},
                        index=pd.DatetimeIndex(index))


def test_floor_pivots_hand_calculation():
    pivots = _floor_pivots(high=110, low=90, close=100)
    assert pivots == {"pivot": 100, "r1": 110, "r2": 120, "s1": 90}


def test_split_sessions_groups_by_exchange_day():
    assert len(split_sessions(bars(days=3))) == 3


def test_intraday_levels_use_previous_session():
    data = bars()
    result = intraday_levels(data)
    previous = split_sessions(data)[-2]
    expected = _floor_pivots(previous["high"].max(), previous["low"].min(), previous["close"].iloc[-1])
    r1 = next(lv for lv in result["levels"] if lv.key == "r1")
    assert r1.price == pytest.approx(expected["r1"])
    assert result["sessions_tested"] == 4


def test_intraday_levels_ignore_todays_later_bars():
    data = bars()
    sessions = split_sessions(data)
    early_today = pd.concat([*sessions[:-1], sessions[-1].iloc[:10]])
    full = intraday_levels(data)
    early = intraday_levels(early_today)
    get = lambda r, k: next(lv for lv in r["levels"] if lv.key == k).price
    for key in ("r1", "r2", "s1"):
        assert get(full, key) == pytest.approx(get(early, key))


def test_intraday_needs_two_sessions():
    assert intraday_levels(bars(days=1)) == {}


def test_break_even():
    assert break_even_move_pct(2.0, 1000.0) == pytest.approx(0.4)
    assert break_even_move_pct(2.0, 0.0) is None
