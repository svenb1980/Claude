from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from app.importers.degiro_csv import parse_export
from app.importers.store import save_export
from app.market.refresh import refresh_all
from app.portfolio.positions import build_portfolio, normalise_currency, replay_transactions
from tests.conftest import PID, ISIN_NL, ISIN_US, make_account_csv, make_transactions_csv


def tx(day, qty, total, fees=1.0, isin="X"):
    return SimpleNamespace(date=dt.date(2024, 1, day), time="10:00", isin=isin, product="P",
                           quantity=qty, total_eur=total, value_eur=None, fees_eur=fees)


def test_average_cost_with_partial_sell():
    # Buy 10 for 1000 and 10 for 1200: 20 shares, average 110. Sell 5 for 700.
    lots = replay_transactions([tx(1, 10, -1000), tx(2, 10, -1200), tx(3, -5, 700)])
    lot = lots["X"]
    assert lot.quantity == 15
    assert lot.cost_eur == pytest.approx(15 * 110)
    assert lot.realised_eur == pytest.approx(700 - 5 * 110)
    assert lot.fees_eur == 3


def test_full_sell_clears_cost_then_rebuy_starts_fresh():
    lot = replay_transactions([tx(1, 10, -1000), tx(2, -10, 1500), tx(3, 5, -600)])["X"]
    assert lot.quantity == 5
    assert lot.cost_eur == 600
    assert lot.realised_eur == 500
    assert lot.first_buy == dt.date(2024, 1, 3)


def test_order_of_input_does_not_matter():
    lots = replay_transactions([tx(3, -5, 700), tx(1, 10, -1000), tx(2, 10, -1200)])
    assert lots["X"].quantity == 15
    assert not lots["X"].warnings


def test_selling_more_than_held_warns_instead_of_going_negative():
    lot = replay_transactions([tx(1, 5, -500), tx(2, -8, 800)])["X"]
    assert lot.quantity == 0
    assert "onvolledig" in lot.warnings[0]
    # Only the 5 known shares count: 5/8 of 800 proceeds minus cost 500.
    assert lot.realised_eur == pytest.approx(0)


def test_minor_currency_units():
    assert normalise_currency("GBp") == ("GBP", 0.01)
    assert normalise_currency("EUR") == ("EUR", 1.0)
    assert normalise_currency(None) == (None, 1.0)


def test_portfolio_value_with_fx_and_cached_prices(factory, session, provider):
    save_export(session, parse_export(make_transactions_csv()), PID)
    save_export(session, parse_export(make_account_csv()), PID)
    session.commit()
    refresh_all(factory, provider)
    session.expire_all()

    portfolio = build_portfolio(session, PID)
    by_isin = {p.isin: p for p in portfolio.positions}
    assert by_isin[ISIN_NL].quantity == 15
    us = by_isin[ISIN_US]
    assert us.quantity == 4
    assert us.value_eur == pytest.approx(4 * provider.series["USC"].iloc[-1] * 0.92)
    assert sum(p.weight_pct for p in portfolio.positions) == pytest.approx(100)
    assert portfolio.unpriced == 0
    assert portfolio.dividends_eur == pytest.approx(21.25 + 6.8 / 1.08)
