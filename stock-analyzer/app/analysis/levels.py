"""Sell levels for the share charts, each with what happened at it historically.

A line alone says nothing, so every level comes with evidence: how often the same rule
fired in the past and how the price moved next, set against the normal move over the
same period. All rolling calculations use data up to that day only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ATR_DAYS = 14
CHANDELIER_DAYS = 22
CHANDELIER_MULT = 3.0
FORWARD_DAYS = 20
SWING_WINDOW = 5
EVIDENCE_DAYS = 1260  # About 5 years
MIN_EVENTS_FOR_TEXT = 5


@dataclass
class Evidence:
    events: int = 0
    held: int | None = None           # Times the price fell back after touching a ceiling
    avg_forward: float | None = None  # Average move after the event
    baseline: float | None = None     # Average move over any period of the same length
    pct_lower: float | None = None    # Share of events with a lower price afterwards
    baseline_lower: float | None = None
    horizon: str = ""                 # e.g. "20 handelsdagen"


@dataclass
class Level:
    key: str
    price: float
    distance_pct: float
    evidence: Evidence = field(default_factory=Evidence)


def _true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    previous = np.concatenate([[close[0]], close[:-1]])
    return np.maximum.reduce([high - low, np.abs(high - previous), np.abs(low - previous)])


def average_true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = ATR_DAYS) -> np.ndarray:
    """Wilder's ATR. Values before `period` bars are NaN."""
    ranges = _true_range(high, low, close)
    atr = np.full(len(ranges), np.nan)
    if len(ranges) < period:
        return atr
    atr[period - 1] = ranges[:period].mean()
    for i in range(period, len(ranges)):
        atr[i] = (atr[i - 1] * (period - 1) + ranges[i]) / period
    return atr


def prepare_ohlc(prices: pd.DataFrame) -> pd.DataFrame:
    """High and low can be missing on older data: fall back to the close."""
    frame = pd.DataFrame({"close": prices["close"].astype(float)})
    for column in ("high", "low"):
        frame[column] = prices[column].astype(float).fillna(frame["close"]) if column in prices else frame["close"]
    return frame.dropna()


def chandelier_series(frame: pd.DataFrame) -> pd.Series:
    """Highest high of the past 22 days minus 3 times the ATR."""
    atr = average_true_range(frame["high"].to_numpy(), frame["low"].to_numpy(), frame["close"].to_numpy())
    highest = frame["high"].rolling(CHANDELIER_DAYS).max().to_numpy()
    return pd.Series(highest - CHANDELIER_MULT * atr, index=frame.index)


def _baseline(close: np.ndarray, days: int) -> tuple[float | None, float | None]:
    if len(close) <= days:
        return None, None
    moves = close[days:] / close[:-days] - 1
    return float(moves.mean()), float((moves < 0).mean())


def _stop_evidence(frame: pd.DataFrame, line: pd.Series) -> Evidence:
    """What happened after the close fell through the stop line?"""
    close = frame["close"].to_numpy()
    values = line.to_numpy()
    crossed = (close[1:] < values[1:]) & (close[:-1] >= values[:-1])
    indices = np.nonzero(crossed)[0] + 1
    usable = indices[indices + FORWARD_DAYS < len(close)]
    evidence = Evidence(horizon=str(FORWARD_DAYS), events=len(usable))
    evidence.baseline, evidence.baseline_lower = _baseline(close, FORWARD_DAYS)
    if len(usable):
        moves = close[usable + FORWARD_DAYS] / close[usable] - 1
        evidence.avg_forward = float(moves.mean())
        evidence.pct_lower = float((moves < 0).mean())
    return evidence


def _ceiling_evidence(frame: pd.DataFrame, level: float, atr: float) -> Evidence:
    """Each past approach of this price from below: was it rejected, or broken?

    Held means the price fell one ATR below the level before closing one ATR above it,
    within the following 20 days.
    """
    close = frame["close"].to_numpy()
    high = frame["high"].to_numpy()
    evidence = Evidence(horizon=str(FORWARD_DAYS), held=0)
    evidence.baseline, evidence.baseline_lower = _baseline(close, FORWARD_DAYS)
    touch_zone = max(atr * 0.25, level * 0.002)
    moves = []
    i = 1
    while i < len(close) - FORWARD_DAYS:
        approached = high[i] >= level - touch_zone and close[i - 1] < level - touch_zone
        if not approached:
            i += 1
            continue
        evidence.events += 1
        moves.append(close[i + FORWARD_DAYS] / close[i] - 1)
        for j in range(i + 1, i + FORWARD_DAYS + 1):
            if close[j] > level + atr:
                break
            if close[j] < level - atr:
                evidence.held += 1
                break
        i += FORWARD_DAYS  # Don't count one episode several times.
    if moves:
        evidence.avg_forward = float(np.mean(moves))
        evidence.pct_lower = float(np.mean(np.array(moves) < 0))
    return evidence


def swing_highs(frame: pd.DataFrame, window: int = SWING_WINDOW) -> list[float]:
    """Highs that are the top of the `window` days on both sides."""
    high = frame["high"].to_numpy()
    found = []
    for i in range(window, len(high) - window):
        if high[i] == high[i - window : i + window + 1].max():
            found.append(float(high[i]))
    return found


def _resistance_levels(frame: pd.DataFrame, price: float, atr: float, count: int = 2) -> list[float]:
    """Cluster swing highs above the price, and keep those touched most often."""
    above = sorted(h for h in swing_highs(frame) if h > price + atr * 0.25)
    clusters: list[list[float]] = []
    for value in above:
        if clusters and value - clusters[-1][-1] <= max(atr * 0.5, value * 0.005):
            clusters[-1].append(value)
        else:
            clusters.append([value])
    # Nearest first; a level touched more than once outranks a one-off further away.
    ranked = sorted(clusters, key=lambda c: (-min(len(c), 2), c[0]))[:count]
    return sorted(float(np.mean(c)) for c in ranked)


def daily_levels(prices: pd.DataFrame) -> dict:
    """Sell levels from daily data. Returns {} with too little history."""
    frame = prepare_ohlc(prices)
    if len(frame) < max(ATR_DAYS, CHANDELIER_DAYS) + 2:
        return {}
    recent = frame.iloc[-EVIDENCE_DAYS:]
    price = float(frame["close"].iloc[-1])
    atr = float(average_true_range(frame["high"].to_numpy(), frame["low"].to_numpy(), frame["close"].to_numpy())[-1])
    line = chandelier_series(frame)
    stop = float(line.iloc[-1])

    def build(key: str, level_price: float, evidence: Evidence) -> Level:
        return Level(key, level_price, (level_price / price - 1) * 100, evidence)

    levels = [build("stop", stop, _stop_evidence(recent, line.iloc[-EVIDENCE_DAYS:]))]
    for n, value in enumerate(_resistance_levels(recent, price, atr), start=1):
        levels.append(build(f"resistance{n}", value, _ceiling_evidence(recent, value, atr)))
    year_high = float(frame["high"].iloc[-252:].max())
    if year_high > price and all(abs(year_high / lv.price - 1) > 0.005 for lv in levels):
        levels.append(build("year_high", year_high, _ceiling_evidence(recent, year_high, atr)))
    levels.sort(key=lambda lv: -lv.price)
    return {"price": price, "atr": atr, "atr_pct": atr / price * 100, "levels": levels,
            "as_of": frame.index[-1].date()}


def _floor_pivots(high: float, low: float, close: float) -> dict[str, float]:
    pivot = (high + low + close) / 3
    return {"pivot": pivot, "r1": 2 * pivot - low, "r2": pivot + high - low, "s1": 2 * pivot - high}


def split_sessions(bars: pd.DataFrame) -> list[pd.DataFrame]:
    """Bars grouped per trading day, in the exchange's own time zone."""
    if bars.empty:
        return []
    days = pd.DatetimeIndex(bars.index).date
    return [group for _, group in bars.groupby(days, sort=True)]


def intraday_levels(bars: pd.DataFrame) -> dict:
    """Levels for today's session from the previous session, with evidence per session.

    For each past session, floor pivots come from the session before it, so nothing
    from that day is known in advance.
    """
    sessions = split_sessions(bars)
    if len(sessions) < 2:
        return {}
    previous, current = sessions[-2], sessions[-1]
    pivots = _floor_pivots(float(previous["high"].max()), float(previous["low"].min()), float(previous["close"].iloc[-1]))
    price = float(current["close"].iloc[-1])

    reached = {"r1": 0, "r2": 0, "s1": 0}
    closed_below = {"r1": 0, "r2": 0, "s1": 0}
    moves = {"r1": [], "r2": [], "s1": []}
    for before, day in zip(sessions[:-2], sessions[1:-1]):
        past = _floor_pivots(float(before["high"].max()), float(before["low"].min()), float(before["close"].iloc[-1]))
        close = day["close"].to_numpy()
        for key in reached:
            hits = (day["high"].to_numpy() >= past[key]) if key != "s1" else (day["low"].to_numpy() <= past[key])
            if hits.any():
                reached[key] += 1
                closed_below[key] += int(close[-1] < past[key])
                moves[key].append(close[-1] / past[key] - 1)

    day_returns = [float(d["close"].iloc[-1] / d["open"].iloc[0] - 1) for d in sessions[1:-1] if "open" in d]
    tested = max(len(sessions) - 2, 0)
    levels = []
    for key in ("r2", "r1", "s1"):
        evidence = Evidence(
            events=reached[key],
            held=closed_below[key],
            avg_forward=float(np.mean(moves[key])) if moves[key] else None,
            baseline=float(np.mean(day_returns)) if day_returns else None,
            horizon="session",
        )
        levels.append(Level(key, pivots[key], (pivots[key] / price - 1) * 100, evidence))
    highs = current["high"].to_numpy()
    lows = current["low"].to_numpy()
    closes = current["close"].to_numpy()
    atr = average_true_range(highs, lows, closes)
    atr_now = float(atr[-1]) if len(closes) >= ATR_DAYS and not np.isnan(atr[-1]) else None
    if atr_now is not None:
        trailing = float(highs.max()) - 3 * atr_now
        levels.append(Level("intraday_stop", trailing, (trailing / price - 1) * 100,
                            Evidence(horizon="session")))
    levels.sort(key=lambda lv: -lv.price)
    return {
        "price": price,
        "levels": levels,
        "sessions_tested": tested,
        "session_date": pd.DatetimeIndex(current.index)[-1].date(),
        "last_bar": pd.DatetimeIndex(current.index)[-1],
        "session_high": float(highs.max()),
        "session_low": float(lows.min()),
    }


def break_even_move_pct(fee_per_order_eur: float, trade_value_eur: float) -> float | None:
    """Rise needed to cover a buy order and a sell order, before tax and spread."""
    if trade_value_eur <= 0:
        return None
    return fee_per_order_eur * 2 / trade_value_eur * 100
