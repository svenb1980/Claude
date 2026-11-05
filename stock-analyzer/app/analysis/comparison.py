"""Compare a portfolio and its stocks with the market, all in EUR.

The portfolio line is a time-weighted return: buying or selling doesn't move it, only how
the holdings perform does. That makes it comparable with an index. Both sides exclude
dividends, because the indices used are price indices.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.service import load_prices
from app.models import FxRate, Product, Transaction
from app.portfolio.positions import QTY_EPSILON, normalise_currency
from app.settings_store import data_version

# (key, Yahoo ticker, quote currency). The label comes from i18n as market_<key>.
MARKETS = (
    ("aex", "^AEX", "EUR"),
    ("europe50", "^STOXX50E", "EUR"),
    ("usa500", "^GSPC", "USD"),
)
MARKET_TICKERS = tuple(ticker for _, ticker, _ in MARKETS)
# (i18n key, months). None means since the first purchase.
PERIODS = (("1m", 1), ("3m", 3), ("6m", 6), ("1y", 12), ("3y", 36), ("5y", 60), ("all", None))
STOCK_COMPARE_MONTHS = 12
# A trade this far from the closing price isn't a real price: usually a split or ISIN
# change, which DEGIRO books as trades without money changing hands.
CORPORATE_ACTION_GAP = 0.5
START_TOLERANCE_DAYS = 7
DAILY_POINTS_YEARS = 2

_cache_lock = threading.Lock()
_cache: dict = {"version": None, "values": {}}


@dataclass
class PortfolioIndex:
    series: pd.Series                    # 100 at the first day with a position
    flagged_days: int = 0                # Trades treated as corporate actions
    excluded: list[str] = field(default_factory=list)  # ISINs without a usable price


def portfolio_index(transactions: Iterable, closes_eur: dict[str, pd.Series]) -> PortfolioIndex:
    """Time-weighted index from transactions and daily closes in EUR, per ISIN.

    Each day: return = gain / (value at yesterday's close + money put in today). A trade
    adds only the difference between its price (with costs) and today's close.
    """
    all_tx = sorted(transactions, key=lambda t: (t.date, t.time or ""))
    excluded = sorted({t.isin for t in all_tx if t.isin not in closes_eur or closes_eur[t.isin].empty})
    priced = [t for t in all_tx if t.isin not in excluded]
    if not priced:
        return PortfolioIndex(pd.Series(dtype=float), 0, excluded)

    first = pd.Timestamp(priced[0].date)
    used = {isin: s for isin, s in closes_eur.items() if isin not in excluded and any(t.isin == isin for t in priced)}
    calendar = pd.DatetimeIndex(sorted(set().union(*(s.index for s in used.values()))))
    calendar = calendar[calendar >= first]
    if len(calendar) == 0:
        return PortfolioIndex(pd.Series(dtype=float), 0, excluded)

    gain = np.zeros(len(calendar))
    base = np.zeros(len(calendar))
    flagged = 0
    for isin, close in used.items():
        prices = close[~close.index.duplicated(keep="last")].reindex(calendar.union(close.index)).ffill().reindex(calendar).to_numpy(dtype=float)
        trades: dict[int, list] = {}
        for tx in (t for t in priced if t.isin == isin):
            # A trade on a day without prices counts on the next day that has them.
            position = int(calendar.searchsorted(pd.Timestamp(tx.date)))
            if position < len(calendar):
                trades.setdefault(position, []).append(tx)
        quantity = 0.0
        for i, price in enumerate(prices):
            if i > 0 and quantity > QTY_EPSILON and not np.isnan(prices[i - 1]) and not np.isnan(price):
                gain[i] += quantity * (price - prices[i - 1])
                base[i] += quantity * prices[i - 1]
            for tx in trades.get(i, []):
                traded = tx.quantity
                if traded < 0:
                    traded = -min(-traded, quantity)
                cash = tx.total_eur
                if cash is None and tx.value_eur is not None:
                    cash = tx.value_eur - (tx.fees_eur or 0.0)
                if cash is not None and tx.quantity != 0 and not np.isnan(price):
                    cash_part = cash * (traded / tx.quantity)
                    trade_gain = traded * price + cash_part
                    if abs(trade_gain) > CORPORATE_ACTION_GAP * abs(traded * price) and abs(traded * price) > 0:
                        flagged += 1
                    else:
                        gain[i] += trade_gain
                        if cash_part < 0:
                            base[i] += -cash_part
                quantity = max(0.0, quantity + traded)

    returns = np.divide(gain, base, out=np.zeros_like(gain), where=base > 0)
    active = np.nonzero(base > 0)[0]
    if len(active) == 0:
        return PortfolioIndex(pd.Series(dtype=float), flagged, excluded)
    start = active[0]
    values = 100 * np.cumprod(1 + returns[start:])
    # The day before the first return is the starting point of 100.
    index = calendar[start:]
    series = pd.Series(values, index=index)
    if start > 0:
        series = pd.concat([pd.Series([100.0], index=[calendar[start - 1]]), series])
    return PortfolioIndex(series, flagged, excluded)


def period_return(series: pd.Series, end: pd.Timestamp, months: int | None, since: pd.Timestamp | None = None) -> float | None:
    """Return up to `end` over the months before it, or from `since`. None if the data doesn't reach back."""
    clean = series.dropna()
    clean = clean[clean.index <= end]
    if clean.empty:
        return None
    target = since if months is None else end - pd.DateOffset(months=months)
    if target is None:
        return None
    if clean.index[0] > target + pd.Timedelta(days=START_TOLERANCE_DAYS):
        return None
    earlier = clean[clean.index <= target]
    start_value = float(earlier.iloc[-1]) if len(earlier) else float(clean.iloc[0])
    return float(clean.iloc[-1]) / start_value - 1 if start_value > 0 else None


def load_fx_series(session: Session, currency: str) -> pd.Series:
    rows = session.execute(
        select(FxRate.date, FxRate.eur_per_unit).where(FxRate.currency == currency).order_by(FxRate.date)
    ).all()
    if not rows:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    return pd.Series([r[1] for r in rows], index=pd.to_datetime([r[0] for r in rows]), dtype=float)


def close_in_eur(session: Session, ticker: str, currency: str | None) -> pd.Series:
    """Daily close in EUR. Empty if the price or exchange rate isn't known."""
    prices = load_prices(session, ticker)
    if prices.empty or not currency:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    close = prices["close"].dropna()
    major, factor = normalise_currency(currency)
    if major == "EUR":
        return close * factor
    fx = load_fx_series(session, major)
    if fx.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    rate = fx.reindex(close.index.union(fx.index)).ffill().bfill().reindex(close.index)
    return close * factor * rate


@dataclass
class StockComparison:
    isin: str
    name: str
    ticker: str
    series: pd.Series
    year_return: float | None
    versus: dict[str, float | None]


@dataclass
class MarketComparison:
    available: bool
    portfolio: pd.Series
    markets: dict[str, pd.Series]
    table: list[dict]                  # One row per line, with a return per period
    stocks: list[StockComparison]
    as_of: pd.Timestamp | None
    flagged: int
    excluded: list[str]
    markets_missing: bool


def _open_isins(transactions: list) -> dict[str, float]:
    quantities: dict[str, float] = {}
    for tx in sorted(transactions, key=lambda t: (t.date, t.time or "")):
        quantity = quantities.get(tx.isin, 0.0)
        quantities[tx.isin] = max(0.0, quantity + tx.quantity)
    return {isin: q for isin, q in quantities.items() if q > QTY_EPSILON}


def build_comparison(session: Session, portfolio_id: int) -> MarketComparison:
    version = data_version(session)
    with _cache_lock:
        if _cache["version"] != version:
            _cache["version"] = version
            _cache["values"] = {}
        if portfolio_id in _cache["values"]:
            return _cache["values"][portfolio_id]

    transactions = session.scalars(select(Transaction).where(Transaction.portfolio_id == portfolio_id)).all()
    isins = {t.isin for t in transactions}
    products = {p.isin: p for p in session.scalars(select(Product)).all() if p.isin in isins}
    closes: dict[str, pd.Series] = {}
    for isin, product in products.items():
        if product.ticker:
            series = close_in_eur(session, product.ticker, product.currency)
            if not series.empty:
                closes[isin] = series

    result = portfolio_index(transactions, closes)
    markets = {key: close_in_eur(session, ticker, currency) for key, ticker, currency in MARKETS}
    markets = {key: series for key, series in markets.items() if not series.empty}

    portfolio = result.series
    candidates = [s.index[-1] for s in [portfolio, *markets.values()] if not s.empty]
    as_of = max(candidates) if candidates else None
    since = portfolio.index[0] if not portfolio.empty else None

    table: list[dict] = []
    if as_of is not None and since is not None:
        lines = [("portfolio", portfolio), *((key, markets[key]) for key, _, _ in MARKETS if key in markets)]
        for key, series in lines:
            table.append({
                "key": key,
                "returns": {name: period_return(series, as_of, months, since) for name, months in PERIODS},
            })

    stocks: list[StockComparison] = []
    open_isins = _open_isins(transactions)
    if as_of is not None:
        for isin in open_isins:
            if isin not in closes:
                continue
            product = products[isin]
            year = period_return(closes[isin], as_of, STOCK_COMPARE_MONTHS)
            versus = {}
            for key, series in markets.items():
                market_year = period_return(series, as_of, STOCK_COMPARE_MONTHS)
                versus[key] = year - market_year if year is not None and market_year is not None else None
            stocks.append(StockComparison(isin, product.name or isin, product.ticker, closes[isin], year, versus))
        stocks.sort(key=lambda s: (s.year_return is None, -(s.year_return or 0.0)))

    value = MarketComparison(
        available=not portfolio.empty,
        portfolio=portfolio,
        markets=markets,
        table=table,
        stocks=stocks,
        as_of=as_of,
        flagged=result.flagged_days,
        excluded=[products[i].name if i in products else i for i in result.excluded],
        markets_missing=len(markets) < len(MARKETS),
    )
    with _cache_lock:
        if _cache["version"] == version:
            _cache["values"][portfolio_id] = value
    return value


def chart_payload(comparison: MarketComparison, labels: dict[str, str]) -> dict:
    """Prices per date for the browser, which restates them from the start of the chosen period."""
    since = comparison.portfolio.index[0]
    frames = {"portfolio": comparison.portfolio}
    frames.update(comparison.markets)
    frames.update({f"s{i}": s.series for i, s in enumerate(comparison.stocks)})
    table = pd.DataFrame(frames).sort_index()
    table = table[table.index >= since].ffill()

    # Daily for recent years; weekly further back keeps the page light on a Pi.
    recent_from = table.index[-1] - pd.DateOffset(years=DAILY_POINTS_YEARS)
    keep = set(np.arange(0, len(table), 5)) | set(np.nonzero(table.index >= recent_from)[0])
    # Each period must start on the same day as in the table on the page.
    for _, months in PERIODS:
        if months is not None:
            position = table.index.searchsorted(table.index[-1] - pd.DateOffset(months=months), side="right") - 1
            if position >= 0:
                keep.add(int(position))
    table = table.iloc[sorted(keep)]

    points = []
    for date, row in table.iterrows():
        point = {"d": date.date().isoformat()}
        for column, value in row.items():
            point[column] = None if pd.isna(value) else round(float(value), 4)
        points.append(point)
    return {
        "points": points,
        "markets": [{"key": key, "label": labels[f"market_{key}"]} for key, _, _ in MARKETS if key in comparison.markets],
        "subjects": [{"key": "portfolio", "label": labels["market_portfolio"]}]
        + [{"key": f"s{i}", "label": s.name} for i, s in enumerate(comparison.stocks)],
        "ranges": [
            {"label": labels[f"period_{name}"], "months": months} for name, months in PERIODS if name != "all"
        ] + [{"label": labels["period_all"], "months": None}],
        "defaultMonths": 12,
    }


def clear_comparison_cache() -> None:
    with _cache_lock:
        _cache["version"] = None
        _cache["values"] = {}
