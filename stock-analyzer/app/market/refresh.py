"""Fetch new market data into the local cache.

Only new days are fetched. If recent stored values no longer match Yahoo's, a split
or dividend has changed the adjusted history, so that ticker is fetched in full again.
A failure for one stock is recorded on that stock, and cached data stays usable.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from app.db import session_scope
from app.market.provider import MarketDataProvider
from app.market.symbols import resolve_missing_symbols
from app.models import DividendHistory, FxRate, Price, Product
from app.portfolio.positions import normalise_currency
from app.settings_store import bump_data_version, get_analysis_settings, get_setting, set_setting

log = logging.getLogger(__name__)

OVERLAP_DAYS = 10
REVISION_TOLERANCE = 0.001  # 0.1%
_refresh_lock = threading.Lock()


def _upsert_prices(session: Session, ticker: str, frame: pd.DataFrame) -> None:
    rows = []
    for date, row in frame.iterrows():
        close = float(row["close"])
        adj = row.get("adj_close")
        adj = close if adj is None or pd.isna(adj) else float(adj)
        volume = row.get("volume")
        rows.append({
            "ticker": ticker, "date": date, "close": close, "adj_close": adj,
            "volume": None if volume is None or pd.isna(volume) else float(volume),
        })
    for start in range(0, len(rows), 400):
        stmt = insert(Price).values(rows[start : start + 400])
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "date"],
            set_={c: stmt.excluded[c] for c in ("close", "adj_close", "volume")},
        )
        session.execute(stmt)


def _stored_prices(session: Session, ticker: str, since: dt.date) -> dict[dt.date, float]:
    rows = session.execute(
        select(Price.date, Price.adj_close).where(Price.ticker == ticker, Price.date >= since)
    ).all()
    return {row[0]: row[1] for row in rows}


def refresh_prices(session: Session, provider: MarketDataProvider, ticker: str) -> None:
    last = session.scalars(
        select(Price.date).where(Price.ticker == ticker).order_by(Price.date.desc()).limit(1)
    ).first()
    if last is None:
        frame = provider.price_history(ticker, None)
        _upsert_prices(session, ticker, frame)
        return
    since = last - dt.timedelta(days=OVERLAP_DAYS)
    frame = provider.price_history(ticker, since)
    stored = _stored_prices(session, ticker, since)
    revised = False
    for date, row in frame.iterrows():
        old = stored.get(date)
        if old and abs(float(row["adj_close"]) / old - 1) > REVISION_TOLERANCE:
            revised = True
            break
    if revised:
        full = provider.price_history(ticker, None)
        if not full.empty:
            session.execute(delete(Price).where(Price.ticker == ticker))
            _upsert_prices(session, ticker, full)
        return
    _upsert_prices(session, ticker, frame)


def refresh_dividends(session: Session, provider: MarketDataProvider, ticker: str) -> None:
    series = provider.dividends(ticker)
    if series.empty:
        return
    rows = [{"ticker": ticker, "ex_date": date, "amount": float(amount)} for date, amount in series.items()]
    for start in range(0, len(rows), 400):
        stmt = insert(DividendHistory).values(rows[start : start + 400])
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "ex_date"], set_={"amount": stmt.excluded.amount}
        )
        session.execute(stmt)


def refresh_fx(session: Session, provider: MarketDataProvider, currency: str) -> None:
    last = session.scalars(
        select(FxRate.date).where(FxRate.currency == currency).order_by(FxRate.date.desc()).limit(1)
    ).first()
    series = provider.fx_history(currency, last)
    if series.empty:
        return
    rows = [{"currency": currency, "date": date, "eur_per_unit": float(rate)} for date, rate in series.items()]
    for start in range(0, len(rows), 400):
        stmt = insert(FxRate).values(rows[start : start + 400])
        stmt = stmt.on_conflict_do_update(
            index_elements=["currency", "date"], set_={"eur_per_unit": stmt.excluded.eur_per_unit}
        )
        session.execute(stmt)


def _refresh_product(session: Session, provider: MarketDataProvider, product: Product) -> None:
    fundamentals = provider.fundamentals(product.ticker) or {}
    product.fundamentals_json = json.dumps(fundamentals)
    product.currency = fundamentals.get("currency") or product.currency
    product.sector = fundamentals.get("sector") or product.sector
    product.country = fundamentals.get("country") or product.country
    product.quote_type = fundamentals.get("quote_type") or product.quote_type
    refresh_prices(session, provider, product.ticker)
    refresh_dividends(session, provider, product.ticker)


def refresh_all(factory: sessionmaker[Session], provider: MarketDataProvider) -> dict:
    """Refresh everything. Returns a status, or {'skipped': True} if already running."""
    if not _refresh_lock.acquire(blocking=False):
        return {"skipped": True}
    started = dt.datetime.now()
    failed = 0
    try:
        with session_scope(factory) as session:
            set_setting(session, "refresh_status", {"running": True, "started": started.isoformat()})
        with session_scope(factory) as session:
            resolve_missing_symbols(session, provider)
            isins = list(session.scalars(select(Product.isin).where(Product.ticker.is_not(None))))
            benchmark = get_analysis_settings(session)["benchmark"]

        currencies: set[str] = set()
        total = len(isins)
        for isin in isins:
            # One commit per stock, so a crash halfway keeps what was already fetched.
            with session_scope(factory) as session:
                product = session.get(Product, isin)
                try:
                    _refresh_product(session, provider, product)
                    product.refresh_error = None
                    product.last_refresh = dt.datetime.now()
                except Exception as exc:
                    log.warning("Refresh failed for %s: %s", product.ticker, exc)
                    session.rollback()
                    product = session.get(Product, isin)
                    product.refresh_error = f"Vernieuwen mislukt: {exc}"[:500]
                    failed += 1
                major, _ = normalise_currency(product.currency)
                if major and major != "EUR":
                    currencies.add(major)

        with session_scope(factory) as session:
            try:
                refresh_prices(session, provider, benchmark)
            except Exception as exc:
                log.warning("Benchmark refresh failed: %s", exc)
                failed += 1
        for currency in sorted(currencies):
            with session_scope(factory) as session:
                try:
                    refresh_fx(session, provider, currency)
                except Exception as exc:
                    log.warning("FX refresh failed for %s: %s", currency, exc)
                    failed += 1

        status = {
            "running": False,
            "finished": dt.datetime.now().isoformat(),
            "total": total,
            "failed": failed,
        }
        with session_scope(factory) as session:
            set_setting(session, "refresh_status", status)
            bump_data_version(session)
        return status
    except Exception as exc:
        log.exception("Refresh failed")
        with session_scope(factory) as session:
            set_setting(session, "refresh_status", {
                "running": False, "finished": dt.datetime.now().isoformat(), "error": str(exc)[:500],
            })
        return {"error": str(exc)}
    finally:
        _refresh_lock.release()


def refresh_status(session: Session) -> dict:
    status = dict(get_setting(session, "refresh_status", {}) or {})
    # A restart can leave "running" behind in the database; the lock is the truth.
    if status.get("running") and not _refresh_lock.locked():
        status["running"] = False
    return status
