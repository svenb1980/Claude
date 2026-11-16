"""Loads data for the analysis and caches results until the data changes."""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.cache import WAIT_FOR_FRESH, ResultCache
from app.analysis.metrics import compute_dividend_metrics, compute_price_metrics
from app.analysis.scoring import ScoreResult, score_holding
from app.models import DividendHistory, Product
from app.portfolio.positions import PortfolioSummary, Position, build_portfolio, normalise_currency
from app.settings_store import data_version, get_analysis_settings, market_version

PRICE_COLUMNS = ["close", "adj_close", "volume", "high", "low"]
PRICE_CACHE_SIZE = 96  # About 25 MB with 25 years of history each.

_signals = ResultCache("signals")
_price_lock = threading.Lock()
_price_cache: OrderedDict[str, tuple[tuple, pd.DataFrame]] = OrderedDict()


@dataclass
class Signal:
    position: Position
    result: ScoreResult
    metrics: dict


def factory_for(session: Session) -> sessionmaker[Session]:
    """Sessions on the same database, for calculations that run in their own thread."""
    return sessionmaker(bind=session.get_bind(), expire_on_commit=False)


def load_prices(session: Session, ticker: str) -> pd.DataFrame:
    """Daily prices, read straight from the database.

    Reads through the DB-API cursor, because building ORM rows and converting them one by
    one took most of the time of a page.
    """
    cursor = session.connection().connection.dbapi_connection.cursor()
    try:
        cursor.execute(
            "SELECT date, close, adj_close, volume, high, low FROM prices WHERE ticker = ? ORDER BY date", (ticker,),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
    if not rows:
        return pd.DataFrame(columns=PRICE_COLUMNS, index=pd.DatetimeIndex([], name="date"), dtype=float)
    dates, *columns = zip(*rows)
    index = pd.DatetimeIndex(pd.to_datetime(np.array(dates, dtype="datetime64[D]")), name="date")
    return pd.DataFrame({name: np.array(values, dtype=float) for name, values in zip(PRICE_COLUMNS, columns)},
                        index=index)


def cached_prices(session: Session, ticker: str) -> pd.DataFrame:
    """Like `load_prices`, but kept until stored prices can have changed.

    For pages and their calculations only. The refresh jobs write prices before raising
    the version, so they use `load_prices`. Callers must not change the returned frame.
    """
    version = market_version(session)
    with _price_lock:
        hit = _price_cache.get(ticker)
        if hit is not None and hit[0] == version:
            _price_cache.move_to_end(ticker)
            return hit[1]
    frame = load_prices(session, ticker)
    with _price_lock:
        _price_cache[ticker] = (version, frame)
        _price_cache.move_to_end(ticker)
        while len(_price_cache) > PRICE_CACHE_SIZE:
            _price_cache.popitem(last=False)
    return frame


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
    prices = cached_prices(session, ticker)
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
    """Signals for the current data, waiting for them if needed."""
    value, _ = _signals.get((portfolio_id, user_id), data_version(session),
                            lambda: _calculate_signals(factory_for(session), portfolio_id, user_id))
    return value


def cached_signals(session: Session, portfolio_id: int, user_id: int, wait: float = WAIT_FOR_FRESH):
    """For pages: ((portfolio, signals, analysis), stale). Stale means a newer result is being calculated."""
    return _signals.get((portfolio_id, user_id), data_version(session),
                        lambda: _calculate_signals(factory_for(session), portfolio_id, user_id), wait=wait)


def _calculate_signals(factory, portfolio_id: int, user_id: int):
    session = factory()
    try:
        return _signals_from(session, portfolio_id, user_id)
    finally:
        session.close()


def _signals_from(session: Session, portfolio_id: int, user_id: int):
    analysis = get_analysis_settings(session, user_id)
    portfolio = build_portfolio(session, portfolio_id)
    bench_prices = cached_prices(session, analysis["benchmark"])
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

    return portfolio, signals, analysis


def clear_cache() -> None:
    from app.analysis.cache import clear_all

    clear_all()
    with _price_lock:
        _price_cache.clear()
