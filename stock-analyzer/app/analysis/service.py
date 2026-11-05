"""Loads data for the analysis and caches results until the data changes."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.metrics import compute_dividend_metrics, compute_price_metrics
from app.analysis.scoring import ScoreResult, score_holding
from app.models import DividendHistory, Price, Product
from app.portfolio.positions import PortfolioSummary, Position, build_portfolio, normalise_currency
from app.settings_store import data_version, get_analysis_settings

_cache_lock = threading.Lock()
_cache: dict = {"version": None, "values": {}}


@dataclass
class Signal:
    position: Position
    result: ScoreResult
    metrics: dict


def load_prices(session: Session, ticker: str) -> pd.DataFrame:
    rows = session.execute(
        select(Price.date, Price.close, Price.adj_close, Price.volume, Price.high, Price.low)
        .where(Price.ticker == ticker)
        .order_by(Price.date)
    ).all()
    columns = ["close", "adj_close", "volume", "high", "low"]
    if not rows:
        return pd.DataFrame(columns=columns, index=pd.DatetimeIndex([]), dtype=float)
    frame = pd.DataFrame(rows, columns=["date", *columns])
    frame["date"] = pd.to_datetime(frame["date"])
    frame[columns] = frame[columns].apply(pd.to_numeric, errors="coerce")
    return frame.set_index("date")


def load_dividends(session: Session, ticker: str) -> pd.Series:
    rows = session.execute(
        select(DividendHistory.ex_date, DividendHistory.amount)
        .where(DividendHistory.ticker == ticker)
        .order_by(DividendHistory.ex_date)
    ).all()
    if not rows:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    return pd.Series([r[1] for r in rows], index=pd.to_datetime([r[0] for r in rows]), dtype=float)


def analyse_ticker(session: Session, ticker: str | None, benchmark: pd.Series | None, risk_free: float) -> dict:
    if not ticker:
        return {}
    prices = load_prices(session, ticker)
    if prices.empty:
        return {}
    metrics = compute_price_metrics(prices["adj_close"], benchmark, risk_free)
    metrics.update(compute_dividend_metrics(prices["close"], load_dividends(session, ticker)))
    return metrics


def _shares(positions: list[Position]) -> tuple[dict, dict]:
    total = sum(p.value_eur for p in positions if p.value_eur is not None)
    sectors: dict[str, float] = {}
    currencies: dict[str, float] = {}
    if total <= 0:
        return sectors, currencies
    for p in positions:
        if p.value_eur is None:
            continue
        if p.sector:
            sectors[p.sector] = sectors.get(p.sector, 0.0) + p.value_eur / total * 100
        major, _ = normalise_currency(p.currency)
        if major:
            currencies[major] = currencies.get(major, 0.0) + p.value_eur / total * 100
    return sectors, currencies


def compute_signals(session: Session, portfolio_id: int, user_id: int) -> tuple[PortfolioSummary, list[Signal], dict]:
    version = data_version(session)
    key = (portfolio_id, user_id)
    with _cache_lock:
        if _cache["version"] != version:
            _cache["version"] = version
            _cache["values"] = {}
        if key in _cache["values"]:
            return _cache["values"][key]

    analysis = get_analysis_settings(session, user_id)
    portfolio = build_portfolio(session, portfolio_id)
    bench_prices = load_prices(session, analysis["benchmark"])
    benchmark = bench_prices["adj_close"] if not bench_prices.empty else None
    products = {p.isin: p for p in session.scalars(select(Product)).all()}
    sectors, currencies = _shares(portfolio.positions)

    signals: list[Signal] = []
    for position in portfolio.positions:
        metrics = analyse_ticker(session, position.ticker, benchmark, analysis["risk_free_pct"])
        major, _ = normalise_currency(position.currency)
        ctx = {
            "weight_pct": position.weight_pct,
            "sector": position.sector,
            "sector_pct": sectors.get(position.sector or "", None),
            "currency": major,
            "currency_pct": currencies.get(major or "", None),
        }
        product = products.get(position.isin)
        fundamentals = product.fundamentals if product else {}
        signals.append(Signal(position, score_holding(metrics, fundamentals, ctx, analysis, position.quote_type), metrics))

    value = (portfolio, signals, analysis)
    with _cache_lock:
        if _cache["version"] == version:
            _cache["values"][key] = value
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache["version"] = None
        _cache["values"] = {}
