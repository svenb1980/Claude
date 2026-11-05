from __future__ import annotations

import datetime as dt
import json

import pytest

from app.dividends.calendar import (
    _pay_lag,
    _project,
    expected_dividends,
    month_view,
    received_dividends,
    year_totals,
)
from app.importers.degiro_csv import parse_export
from app.importers.store import save_export
from app.market.refresh import refresh_all
from app.models import DividendHistory, Product
from tests.conftest import ISIN_NL, ISIN_US, make_account_csv, make_transactions_csv

TODAY = dt.date(2026, 11, 5)


def _seed(factory, session, provider):
    save_export(session, parse_export(make_transactions_csv()))
    save_export(session, parse_export(make_account_csv()))
    session.commit()
    refresh_all(factory, provider)
    session.expire_all()


def test_received_combines_gross_and_tax(factory, session, provider):
    _seed(factory, session, provider)
    items = {r.isin: r for r in received_dividends(session)}
    nl = items[ISIN_NL]
    assert (nl.gross, nl.tax, nl.net) == (25.0, -3.75, 21.25)
    assert nl.net_eur == 21.25
    assert nl.tax_rate == pytest.approx(0.15)


def test_received_uses_degiros_own_exchange_rate(factory, session, provider):
    _seed(factory, session, provider)
    us = next(r for r in received_dividends(session) if r.isin == ISIN_US)
    assert us.gross == 8.0
    assert us.gross_eur == pytest.approx(8.0 / 1.08)
    assert us.net_eur == pytest.approx(6.8 / 1.08)


def test_reversed_dividend_nets_out(session):
    raw = make_account_csv() + (
        f'05-05-2025,09:00,05-05-2025,ACME NV,{ISIN_NL},Dividend,,EUR,"-25,00",EUR,"1,00",\n'
        f'05-05-2025,09:00,05-05-2025,ACME NV,{ISIN_NL},Dividendbelasting,,EUR,"3,75",EUR,"1,00",\n'
    ).encode()
    save_export(session, parse_export(raw))
    assert [r.isin for r in received_dividends(session)] == [ISIN_US]


def test_pay_lag_from_own_receipts():
    ex = [dt.date(2024, 4, 25), dt.date(2025, 4, 25)]
    receipts = [dt.date(2024, 5, 5), dt.date(2025, 5, 7)]
    assert _pay_lag(ex, receipts) == 11
    assert _pay_lag(ex, []) is None
    assert _pay_lag(ex, [dt.date(2025, 12, 25)]) is None  # Too long after: not related.


def test_projection_quarterly():
    history = [(dt.date(2026, m, 10), 2.0) for m in (3, 6, 9)] + [(dt.date(2025, 12, 10), 2.0)]
    history.sort()
    result = _project(history, [d for d, _ in history], TODAY, TODAY + dt.timedelta(days=365))
    assert [d for d, _ in result] == [dt.date(2026, 12, 10), dt.date(2027, 3, 10), dt.date(2027, 6, 10), dt.date(2027, 9, 10)]


def test_projection_keeps_final_and_interim_amounts():
    history = [(dt.date(2025, 4, 25), 1.4), (dt.date(2025, 8, 20), 0.5),
               (dt.date(2026, 4, 25), 1.5), (dt.date(2026, 8, 20), 0.6)]
    result = dict(_project(history, [d for d, _ in history], TODAY, TODAY + dt.timedelta(days=365)))
    assert result[dt.date(2027, 4, 26)] == 1.5  # 25 April 2027 is a Sunday
    assert result[dt.date(2027, 8, 20)] == 0.6


def test_interim_that_was_skipped_this_year_is_not_projected():
    history = [(dt.date(2025, 8, 20), 0.5), (dt.date(2026, 4, 25), 1.5)]
    result = dict(_project(history, [d for d, _ in history], TODAY, TODAY + dt.timedelta(days=365)))
    assert list(result) == [dt.date(2027, 4, 26)]


def test_estimates_never_land_on_a_weekend():
    history = [(dt.date(2026, m, 10), 1.0) for m in range(1, 11)]
    result = _project(history, [d for d, _ in history], TODAY, TODAY + dt.timedelta(days=365))
    assert result
    assert all(d.weekday() < 5 for d, _ in result)


def test_projection_stops_for_a_dividend_that_ended():
    assert _project([(dt.date(2024, 1, 10), 1.0)], [], TODAY, TODAY + dt.timedelta(days=365)) == []


def test_projection_does_not_repeat_a_payment_already_made_this_year():
    # Paid late last year, earlier this year: last year's date must not add a second one.
    history = [(dt.date(2025, 11, 20), 1.0), (dt.date(2026, 10, 20), 1.1)]
    result = _project(history, [d for d, _ in history], TODAY, TODAY + dt.timedelta(days=365))
    assert [d for d, _ in result] == [dt.date(2027, 10, 20)]


def test_expected_amounts_use_current_shares_and_past_withholding(factory, session, provider):
    _seed(factory, session, provider)
    expected = expected_dividends(session, today=TODAY)
    acme = [e for e in expected if e.isin == ISIN_NL]
    assert len(acme) == 1
    item = acme[0]
    assert item.status == "estimated"
    assert item.ex_date == dt.date(2027, 4, 26)
    assert item.quantity == 15
    assert item.per_share == 1.3
    assert item.gross_eur == pytest.approx(19.5)
    assert item.net_eur == pytest.approx(19.5 * 0.85)


def test_expected_converts_foreign_currency_quarterly(factory, session, provider):
    _seed(factory, session, provider)
    us = [e for e in expected_dividends(session, today=TODAY) if e.isin == ISIN_US]
    assert len(us) == 4
    assert us[0].gross_eur == pytest.approx(4 * 2.0 * 0.92)
    assert us[0].net_eur == pytest.approx(4 * 2.0 * 0.92 * 0.85)


def test_pay_date_estimated_from_own_history(factory, session, provider):
    _seed(factory, session, provider)
    # ACME: ex-date 25-04-2025, received 05-05-2025, so 10 days later.
    item = next(e for e in expected_dividends(session, today=TODAY) if e.isin == ISIN_NL)
    assert item.pay_basis == "history"
    assert item.pay_date == dt.date(2027, 5, 6)


def test_no_history_uses_default_lag_and_unknown_net(factory, session, provider):
    save_export(session, parse_export(make_transactions_csv()))
    session.commit()
    refresh_all(factory, provider)
    session.expire_all()
    item = next(e for e in expected_dividends(session, today=TODAY) if e.isin == ISIN_NL)
    assert item.pay_basis == "default"
    assert item.net_eur is None
    assert item.gross_eur is not None
    # An unknown net total stays unknown instead of showing as zero.
    totals = year_totals(2027, [], expected_dividends(session, today=TODAY))
    assert totals["expected_gross"] > 0
    assert totals["expected_net"] is None


def test_announced_future_dividend_is_confirmed(factory, session, provider):
    _seed(factory, session, provider)
    session.add(DividendHistory(ticker="ACME.AS", ex_date=dt.date(2026, 12, 1), amount=2.0))
    session.commit()
    item = next(e for e in expected_dividends(session, today=TODAY) if e.ex_date == dt.date(2026, 12, 1))
    assert item.status == "confirmed"
    assert item.per_share == 2.0


def test_announced_date_without_amount_says_so(factory, session, provider):
    _seed(factory, session, provider)
    product = session.get(Product, ISIN_NL)
    product.fundamentals_json = json.dumps({"next_ex_date": "2026-12-15", "next_pay_date": "2026-12-28"})
    session.commit()
    item = next(e for e in expected_dividends(session, today=TODAY) if e.ex_date == dt.date(2026, 12, 15))
    assert item.status == "date_confirmed"
    assert item.pay_date == dt.date(2026, 12, 28)
    assert item.pay_basis == "confirmed"


def test_went_ex_recently_and_unpaid_counts_shares_at_that_date(factory, session, provider):
    _seed(factory, session, provider)
    session.add(DividendHistory(ticker="ACME.AS", ex_date=dt.date(2026, 11, 1), amount=1.0))
    session.commit()
    item = next(e for e in expected_dividends(session, today=TODAY) if e.ex_date == dt.date(2026, 11, 1))
    assert item.status == "confirmed"
    assert item.quantity == 15
    assert item.pay_date >= TODAY


def test_sold_position_expects_nothing(factory, session, provider):
    raw = make_transactions_csv().decode() + (
        f'01-03-2026,10:00,ACME NV,{ISIN_NL},EAM,XAMS,-15,"130,00",EUR,"1950,00",EUR,"1950,00",EUR,,"-2,00",EUR,"1948,00",EUR,o\n'
    )
    save_export(session, parse_export(raw.encode()))
    session.commit()
    refresh_all(factory, provider)
    session.expire_all()
    assert not [e for e in expected_dividends(session, today=TODAY) if e.isin == ISIN_NL]


def test_month_view_and_totals(factory, session, provider):
    _seed(factory, session, provider)
    received = received_dividends(session)
    expected = expected_dividends(session, today=TODAY)
    weeks = month_view(2025, 5, received, expected)
    cells = [c for week in weeks for c in week if c.date == dt.date(2025, 5, 5)]
    assert cells[0].received[0].isin == ISIN_NL
    assert all(len(week) == 7 for week in weeks)

    totals = year_totals(2025, received, expected)
    assert totals["received_net"] == pytest.approx(21.25 + 6.8 / 1.08)
    assert totals["months"][4]["received"] == pytest.approx(21.25)
    future = year_totals(2027, received, expected)
    assert future["expected_gross"] > 0
