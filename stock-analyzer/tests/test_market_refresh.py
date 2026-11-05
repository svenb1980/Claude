from __future__ import annotations

import pandas as pd

from app.importers.degiro_csv import parse_export
from app.importers.store import save_export
from app.market.refresh import refresh_all, refresh_prices
from app.market.symbols import set_manual_ticker
from app.models import Price, Product
from tests.conftest import PID, ISIN_NL, ISIN_US, make_transactions_csv


def _seed(session):
    save_export(session, parse_export(make_transactions_csv()), PID)
    session.commit()


def test_full_refresh_links_tickers_and_stores_data(factory, session, provider):
    _seed(session)
    status = refresh_all(factory, provider)
    assert status["failed"] == 0
    session.expire_all()
    product = session.get(Product, ISIN_NL)
    assert product.ticker == "ACME.AS"
    assert product.sector == "Technology"
    assert session.query(Price).filter_by(ticker="ACME.AS").count() == 1500
    assert session.query(Price).filter_by(ticker="IWDA.AS").count() == 1500


def test_second_refresh_only_fetches_recent_days(factory, session, provider):
    _seed(session)
    refresh_all(factory, provider)
    provider.history_calls.clear()
    refresh_all(factory, provider)
    assert provider.history_calls
    assert all(start is not None for _, start in provider.history_calls)


def test_changed_history_triggers_full_refetch(session, provider):
    refresh_prices(session, provider, "ACME.AS")
    # A 2-for-1 split rewrites all stored history on Yahoo's side.
    provider.series["ACME.AS"] = provider.series["ACME.AS"] / 2
    provider.history_calls.clear()
    refresh_prices(session, provider, "ACME.AS")
    assert provider.history_calls[-1] == ("ACME.AS", None)
    stored = session.query(Price).filter_by(ticker="ACME.AS").order_by(Price.date).first().close
    assert abs(stored - provider.series["ACME.AS"].iloc[0]) < 1e-9


def test_one_failing_stock_keeps_the_rest_and_its_cache(factory, session, provider):
    _seed(session)
    refresh_all(factory, provider)
    session.expire_all()
    before = session.query(Price).filter_by(ticker="USC").count()

    provider.fail_for.add("USC")
    status = refresh_all(factory, provider)
    assert status["failed"] == 1
    session.expire_all()
    assert "mislukt" in session.get(Product, ISIN_US).refresh_error
    assert session.get(Product, ISIN_NL).refresh_error is None
    assert session.query(Price).filter_by(ticker="USC").count() == before


def test_manual_ticker_is_kept(factory, session, provider):
    _seed(session)
    session.get(Product, ISIN_NL).ticker = None
    set_manual_ticker(session, ISIN_NL, "acme.de ")
    session.commit()
    provider.series["ACME.DE"] = provider.series["ACME.AS"]
    refresh_all(factory, provider)
    session.expire_all()
    product = session.get(Product, ISIN_NL)
    assert product.ticker == "ACME.DE"
    assert product.ticker_source == "manual"


def test_unknown_isin_is_reported(factory, session, provider):
    _seed(session)
    provider.resolve_isin = lambda *_: None
    refresh_all(factory, provider)
    session.expire_all()
    assert "handmatig" in session.get(Product, ISIN_NL).refresh_error
    assert isinstance(provider.price_history("IWDA.AS", None), pd.DataFrame)
