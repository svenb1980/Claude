from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from app.analysis.comparison import build_comparison, chart_payload, close_in_eur, period_return, portfolio_index
from app.i18n.nl import T
from app.importers.degiro_csv import parse_export
from app.importers.store import save_export
from app.market.refresh import refresh_all, refresh_prices
from app.models import FxRate
from tests.conftest import PID, ISIN_NL, make_transactions_csv, synthetic_prices


def tx(day, qty, total, isin="X", fees=0.0):
    return SimpleNamespace(date=dt.date(2026, 1, day), time="10:00", isin=isin, quantity=qty,
                           total_eur=total, value_eur=None, fees_eur=fees)


def closes(values, start="2026-01-05"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_index_follows_the_price():
    # Bought at the close of 5 January; the price then rises 10% and falls back.
    result = portfolio_index([tx(5, 10, -1000)], {"X": closes([100, 110, 99])})
    assert result.series.iloc[0] == pytest.approx(100)
    assert result.series.iloc[-2] == pytest.approx(110)
    assert result.series.iloc[-1] == pytest.approx(99)


def test_buying_more_does_not_move_the_line():
    prices = closes([100, 110, 110, 121])
    single = portfolio_index([tx(5, 10, -1000)], {"X": prices})
    extra = portfolio_index([tx(5, 10, -1000), tx(7, 90, -9900)], {"X": prices})
    assert extra.series.iloc[-1] == pytest.approx(single.series.iloc[-1])


def test_small_position_then_large_buy_is_time_weighted():
    # A stock doubles while you hold 1 share, then you buy 99 more: the return stays +100%.
    prices = closes([100, 200, 200])
    result = portfolio_index([tx(5, 1, -100), tx(7, 99, -19800)], {"X": prices})
    assert result.series.iloc[-1] == pytest.approx(200)


def test_selling_everything_freezes_the_line_until_the_next_buy():
    prices = closes([100, 110, 220, 220, 242])
    result = portfolio_index([tx(5, 10, -1000), tx(6, -10, 1100), tx(8, 10, -2200)], {"X": prices})
    assert result.series.loc["2026-01-07"] == pytest.approx(110)
    assert result.series.iloc[-1] == pytest.approx(110 * 1.1)


def test_costs_lower_the_return():
    result = portfolio_index([tx(5, 10, -1010)], {"X": closes([100, 100])})
    assert result.series.iloc[-1] < 100


def test_two_stocks_are_weighted_by_value():
    result = portfolio_index(
        [tx(5, 10, -1000, "A"), tx(5, 30, -3000, "B")],
        {"A": closes([100, 120]), "B": closes([100, 100])},
    )
    assert result.series.iloc[-1] == pytest.approx(105)


def test_split_booked_as_trades_gives_no_false_gain():
    # Yahoo's history is split-adjusted, so the 2-for-1 split shows no price jump.
    prices = closes([50, 50, 50])
    transactions = [
        tx(5, 10, -500),
        SimpleNamespace(date=dt.date(2026, 1, 7), time="09:00", isin="X", quantity=-10, total_eur=0.0, value_eur=None, fees_eur=0.0),
        SimpleNamespace(date=dt.date(2026, 1, 7), time="09:01", isin="X", quantity=20, total_eur=0.0, value_eur=None, fees_eur=0.0),
    ]
    result = portfolio_index(transactions, {"X": prices})
    assert result.series.iloc[-1] == pytest.approx(100)
    assert result.flagged_days == 2


def test_stock_without_price_is_left_out_and_reported():
    result = portfolio_index([tx(5, 10, -1000), tx(5, 5, -500, "GEEN")], {"X": closes([100, 110])})
    assert result.excluded == ["GEEN"]
    assert result.series.iloc[-1] == pytest.approx(110)


def test_trade_on_a_day_without_prices_counts_next_day():
    prices = closes([100, 110], start="2026-01-05")
    result = portfolio_index([tx(3, 10, -1000)], {"X": prices})  # 3 January 2026 is a Saturday
    assert result.series.iloc[-1] == pytest.approx(110)


def test_no_transactions():
    result = portfolio_index([], {})
    assert result.series.empty


def test_period_return():
    series = pd.Series([100.0, 110.0, 121.0], index=pd.to_datetime(["2025-11-03", "2026-05-01", "2026-11-03"]))
    end = pd.Timestamp("2026-11-03")
    assert period_return(series, end, 12) == pytest.approx(0.21)
    assert period_return(series, end, 6) == pytest.approx(0.1)
    assert period_return(series, end, 60) is None
    assert period_return(series, end, None, pd.Timestamp("2026-05-01")) == pytest.approx(0.1)


def test_period_return_ignores_later_data():
    series = pd.Series([100.0, 110.0, 999.0], index=pd.to_datetime(["2025-11-03", "2026-11-03", "2026-11-04"]))
    assert period_return(series, pd.Timestamp("2026-11-03"), 12) == pytest.approx(0.1)


def test_us_index_is_converted_to_euro(session, provider):
    provider.series["^GSPC"] = synthetic_prices(seed=9)
    refresh_prices(session, provider, "^GSPC")
    last = provider.series["^GSPC"].index[-1].date()
    session.add(FxRate(currency="USD", date=dt.date(2020, 1, 1), eur_per_unit=0.5))
    session.add(FxRate(currency="USD", date=last, eur_per_unit=1.0))
    session.flush()
    euro = close_in_eur(session, "^GSPC", "USD")
    assert euro.iloc[-1] == pytest.approx(provider.series["^GSPC"].iloc[-1])
    assert euro.iloc[-2] == pytest.approx(provider.series["^GSPC"].iloc[-2] * 0.5)


def test_full_comparison_from_imported_portfolio(factory, session, provider):
    provider.series.update({"^AEX": synthetic_prices(seed=5, days=3000), "^STOXX50E": synthetic_prices(seed=6, days=3000),
                            "^GSPC": synthetic_prices(seed=7, days=3000)})
    save_export(session, parse_export(make_transactions_csv()), PID)
    session.commit()
    refresh_all(factory, provider)
    session.expire_all()

    comparison = build_comparison(session, PID)
    assert comparison.available
    assert not comparison.markets_missing
    assert {row["key"] for row in comparison.table} == {"portfolio", "aex", "europe50", "usa500"}
    assert {s.isin for s in comparison.stocks} >= {ISIN_NL}
    acme = next(s for s in comparison.stocks if s.isin == ISIN_NL)
    assert acme.versus["aex"] == pytest.approx(
        acme.year_return - period_return(comparison.markets["aex"], comparison.as_of, 12)
    )

    labels = T
    payload = chart_payload(comparison, labels)
    assert [m["key"] for m in payload["markets"]] == ["aex", "europe50", "usa500"]
    assert payload["subjects"][0]["key"] == "portfolio"
    assert len(payload["points"]) > 100
    dates = [p["d"] for p in payload["points"]]
    assert dates == sorted(dates)
    # Older data is thinned out, but the period starts in the table are kept.
    end = comparison.portfolio.index[-1]
    for months in (36, 60):
        start = comparison.portfolio[comparison.portfolio.index <= end - pd.DateOffset(months=months)]
        if len(start):
            assert start.index[-1].date().isoformat() in dates


def test_markets_not_loaded_yet_is_reported(factory, session, provider):
    save_export(session, parse_export(make_transactions_csv()), PID)
    session.commit()
    refresh_all(factory, provider)
    session.expire_all()
    comparison = build_comparison(session, PID)
    assert comparison.available
    assert comparison.markets_missing
