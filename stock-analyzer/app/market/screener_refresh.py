"""Keep the screener's data current, a batch of stocks at a time.

Each stock takes three Yahoo requests, so about 1,000 stocks can't be refreshed in one
go without being blocked. Each run handles the stocks with the oldest data, and a
rate-limit response ends the run early. The next run continues where this one stopped.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.metrics import compute_dividend_metrics, compute_price_metrics
from app.analysis.service import load_dividends, load_prices
from app.db import session_scope
from app.market.provider import MarketDataProvider
from app.market.refresh import refresh_dividends, refresh_fx, refresh_prices
from app.models import ScreenerStock
from app.portfolio.positions import latest_fx, normalise_currency
from app.settings_store import DEFAULT_BENCHMARK, bump_data_version, get_setting, set_setting

log = logging.getLogger(__name__)

UNIVERSE_FILE = Path(__file__).parent / "universe.json"
DEFAULT_BATCH = 200
RATE_LIMIT_WORDS = ("rate limit", "too many requests", "429")
STOP_AFTER_FAILURES_IN_A_ROW = 15
_lock = threading.Lock()


def seed_universe(session: Session) -> int:
    """Add stocks from the shipped list. Existing rows and manual changes stay as they are."""
    if not UNIVERSE_FILE.exists():
        return 0
    known = {row[0]: row[1] for row in session.execute(select(ScreenerStock.ticker, ScreenerStock.indices)).all()}
    added = 0
    for item in json.loads(UNIVERSE_FILE.read_text(encoding="utf-8")):
        indices = ", ".join(item.get("indices", []))
        if item["ticker"] in known:
            continue
        session.add(ScreenerStock(ticker=item["ticker"], name=item.get("name", ""), indices=indices))
        added += 1
    session.flush()
    return added


def add_manual_tickers(session: Session, tickers: list[str]) -> int:
    added = 0
    for ticker in tickers:
        if session.get(ScreenerStock, ticker) is None:
            session.add(ScreenerStock(ticker=ticker, name=ticker, source="manual"))
            added += 1
    session.flush()
    return added


def _rows_needing_refresh(session: Session, limit: int) -> list[str]:
    rows = session.execute(
        select(ScreenerStock.ticker)
        .where(ScreenerStock.enabled.is_(True))
        .order_by(ScreenerStock.last_refresh.is_not(None), ScreenerStock.last_refresh)
        .limit(limit)
    ).all()
    return [row[0] for row in rows]


def _is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(word in text for word in RATE_LIMIT_WORDS) or "ratelimit" in text


def build_stock_data(session: Session, ticker: str, fundamentals: dict, benchmark) -> dict:
    prices = load_prices(session, ticker)
    if prices.empty:
        return {}
    metrics = compute_price_metrics(prices["adj_close"], benchmark)
    metrics.update(compute_dividend_metrics(prices["close"], load_dividends(session, ticker)))
    if metrics.get("last_date"):
        metrics["last_date"] = metrics["last_date"].isoformat()
    if "volume" in prices:
        recent = prices.iloc[-60:]
        turnover = (recent["close"] * recent["volume"]).mean()
        major, factor = normalise_currency(fundamentals.get("currency"))
        fx = latest_fx(session, major)
        if fx is not None and turnover == turnover:
            metrics["turnover_eur_m"] = float(turnover) * factor * fx / 1e6
    return {"metrics": metrics, "fundamentals": fundamentals}


def refresh_stock(session: Session, provider: MarketDataProvider, stock: ScreenerStock, benchmark) -> None:
    fundamentals = provider.fundamentals(stock.ticker) or {}
    if not fundamentals.get("currency") and not fundamentals.get("name"):
        raise LookupError("Yahoo kent deze ticker niet")
    refresh_prices(session, provider, stock.ticker)
    refresh_dividends(session, provider, stock.ticker)
    major, _ = normalise_currency(fundamentals.get("currency"))
    if major and major != "EUR" and latest_fx(session, major) is None:
        refresh_fx(session, provider, major)
    stock.name = fundamentals.get("name") or stock.name
    stock.sector = fundamentals.get("sector") or stock.sector
    stock.country = fundamentals.get("country") or stock.country
    stock.currency = fundamentals.get("currency") or stock.currency
    stock.quote_type = fundamentals.get("quote_type") or stock.quote_type
    stock.isin = fundamentals.get("isin") or stock.isin
    stock.data_json = json.dumps(build_stock_data(session, stock.ticker, fundamentals, benchmark))
    stock.refresh_error = None
    stock.last_refresh = dt.datetime.now()


def refresh_batch(factory: sessionmaker[Session], provider: MarketDataProvider, batch: int = DEFAULT_BATCH) -> dict:
    if not _lock.acquire(blocking=False):
        return {"skipped": True}
    done = failed = 0
    in_a_row = 0
    stopped_by_limit = False
    try:
        with session_scope(factory) as session:
            set_setting(session, "screener_status", {"running": True, "started": dt.datetime.now().isoformat()})
            tickers = _rows_needing_refresh(session, batch)
        with session_scope(factory) as session:
            try:
                refresh_prices(session, provider, DEFAULT_BENCHMARK)
            except Exception as exc:
                log.warning("Benchmark refresh failed: %s", exc)
            frame = load_prices(session, DEFAULT_BENCHMARK)
        benchmark = frame["adj_close"] if not frame.empty else None

        for ticker in tickers:
            limited = False
            with session_scope(factory) as session:
                stock = session.get(ScreenerStock, ticker)
                try:
                    refresh_stock(session, provider, stock, benchmark)
                    done += 1
                    in_a_row = 0
                except Exception as exc:
                    session.rollback()
                    limited = _is_rate_limit(exc)
                    if not limited:
                        stock = session.get(ScreenerStock, ticker)
                        stock.refresh_error = str(exc)[:300]
                        # Moves it to the back of the queue, so a bad ticker can't block the rest.
                        stock.last_refresh = stock.last_refresh or dt.datetime.now()
                        failed += 1
                        in_a_row += 1
            if limited or in_a_row >= STOP_AFTER_FAILURES_IN_A_ROW:
                stopped_by_limit = True
                log.warning("Screener refresh stopped early after %s stocks", done)
                break

        status = {
            "running": False, "finished": dt.datetime.now().isoformat(),
            "done": done, "failed": failed, "stopped_early": stopped_by_limit,
        }
        with session_scope(factory) as session:
            set_setting(session, "screener_status", status)
            bump_data_version(session)
        return status
    except Exception as exc:
        log.exception("Screener refresh failed")
        with session_scope(factory) as session:
            set_setting(session, "screener_status", {"running": False, "error": str(exc)[:300]})
        return {"error": str(exc)}
    finally:
        _lock.release()


def screener_status(session: Session) -> dict:
    status = dict(get_setting(session, "screener_status", {}) or {})
    if status.get("running") and not _lock.locked():
        status["running"] = False
    return status


def screener_counts(session: Session) -> dict:
    rows = session.execute(select(ScreenerStock.enabled, ScreenerStock.last_refresh, ScreenerStock.refresh_error)).all()
    enabled = [r for r in rows if r[0]]
    return {
        "total": len(enabled),
        "with_data": sum(1 for r in enabled if r[1] is not None and r[2] is None),
        "errors": sum(1 for r in enabled if r[2]),
    }
