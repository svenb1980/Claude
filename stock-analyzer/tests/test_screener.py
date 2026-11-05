from __future__ import annotations

import json
import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from app.analysis.screener import PRESETS, portfolio_profile, run_screen, score_stock
from app.market.screener_refresh import add_manual_tickers, refresh_batch, screener_counts, seed_universe
from app.models import Price, ScreenerStock
from tests.conftest import FakeProvider, synthetic_prices

GOOD = {
    "metrics": {"pays_dividend": True, "yield": 0.04, "yield_percentile": 80, "dividend_streak": 8, "turnover_eur_m": 50.0,
                "price_vs_sma200": 0.1, "sma50_vs_sma200": 0.05, "slope_12m": 0.2, "r3": 0.05, "r6": 0.1, "r12": 0.2,
                "relative_12m": 0.1, "rsi": 55, "vol_1y": 0.2, "max_dd_5y": -0.2, "sharpe_3y": 1.0, "beta_3y": 0.9,
                "last_date": "2026-11-03"},
    "fundamentals": {"sector": "Healthcare", "country": "Netherlands", "revenue_growth": 0.15, "earnings_growth": 0.2,
                     "return_on_equity": 0.2, "profit_margin": 0.2, "debt_to_equity": 40.0, "trailing_pe": 14.0,
                     "forward_pe": 12.0, "price_to_book": 2.0, "payout_ratio": 0.4, "spread_pct": 0.05},
}
BAD = {
    "metrics": {"pays_dividend": False, "turnover_eur_m": 1.0, "price_vs_sma200": -0.2, "sma50_vs_sma200": -0.1,
                "slope_12m": -0.3, "r3": -0.15, "r6": -0.25, "r12": -0.35, "relative_12m": -0.25, "rsi": 25, "vol_1y": 0.6,
                "max_dd_5y": -0.7, "sharpe_3y": -0.5, "beta_3y": 1.8, "last_date": "2026-11-03"},
    "fundamentals": {"sector": "Technology", "country": "Netherlands", "revenue_growth": -0.2, "earnings_growth": -0.4,
                     "return_on_equity": -0.1, "profit_margin": -0.1, "debt_to_equity": 400.0, "trailing_pe": 60.0,
                     "forward_pe": 50.0, "price_to_book": 15.0, "spread_pct": 1.5},
}
EMPTY_PROFILE = {"has_positions": False, "sectors": {}, "countries": {}, "held_tickers": set(), "held_isins": set(), "held_names": set()}


def _stock(session, ticker, data, name=None, **kw):
    session.add(ScreenerStock(ticker=ticker, name=name or ticker, data_json=json.dumps(data),
                              last_refresh=dt.datetime(2026, 11, 3), **kw))
    session.flush()


def test_good_results_rank_above_bad(session):
    _stock(session, "GOOD.AS", GOOD, sector="Healthcare")
    _stock(session, "BAD.AS", BAD, sector="Technology")
    results = run_screen(session, EMPTY_PROFILE)
    assert [r.ticker for r in results] == ["GOOD.AS", "BAD.AS"]
    assert results[0].label == "candidate"
    assert results[1].label == "weak"
    assert results[0].top_reasons


def test_presets_change_the_ranking():
    payer = json.loads(json.dumps(BAD))
    payer["metrics"].update(pays_dividend=True, **{"yield": 0.05}, dividend_streak=12)
    payer["fundamentals"]["payout_ratio"] = 0.4
    high_dividend, _, _ = score_stock(payer, EMPTY_PROFILE, PRESETS["dividend"])
    no_dividend, _, _ = score_stock(BAD, EMPTY_PROFILE, PRESETS["dividend"])
    assert high_dividend > no_dividend
    momentum_only, _, _ = score_stock(payer, EMPTY_PROFILE, PRESETS["momentum"])
    assert momentum_only < high_dividend


def test_held_stocks_are_excluded(session):
    _stock(session, "GOOD.AS", GOOD)
    _stock(session, "OTHER.DE", GOOD, name="Same Company NV")
    _stock(session, "FREE.AS", GOOD)
    profile = {**EMPTY_PROFILE, "held_tickers": {"GOOD.AS"}, "held_names": {"same company nv"}}
    assert [r.ticker for r in run_screen(session, profile)] == ["FREE.AS"]


def test_stock_in_an_empty_sector_scores_higher_for_spreading():
    profile = {"has_positions": True, "sectors": {"Technology": 60.0}, "countries": {"Netherlands": 60.0}}
    tech = json.loads(json.dumps(GOOD))
    tech["fundamentals"]["sector"] = "Technology"
    new_sector, _, _ = score_stock(GOOD, profile, PRESETS["spreading"])
    same_sector, _, _ = score_stock(tech, profile, PRESETS["spreading"])
    assert new_sector > same_sector


def test_missing_data_means_insufficient_not_neutral(session):
    _stock(session, "THIN.AS", {"metrics": {"last_date": "2026-11-03"}, "fundamentals": {}})
    result = run_screen(session, EMPTY_PROFILE)[0]
    assert result.label == "insufficient"


def test_incredible_yield_is_not_rewarded():
    odd = json.loads(json.dumps(GOOD))
    odd["metrics"]["yield"] = 0.8
    _, _, factors = score_stock(odd, EMPTY_PROFILE, PRESETS["dividend"])
    dividend = next(f for f in factors if f.key == "dividend")
    assert any("ongeloofwaardig" in note for note in dividend.notes)
    assert "dividendrendement" in dividend.missing


def test_extreme_earnings_growth_is_not_rewarded():
    odd = json.loads(json.dumps(GOOD))
    odd["fundamentals"]["earnings_growth"] = 22.82
    _, _, factors = score_stock(odd, EMPTY_PROFILE, PRESETS["results"])
    results = next(f for f in factors if f.key == "results")
    assert any("vergelijkingsbasis" in note for note in results.notes)
    assert not any("Winstgroei:" in text for _, text in results.reasons)


def test_debt_ratio_does_not_count_for_banks():
    bank = json.loads(json.dumps(GOOD))
    bank["fundamentals"].update(sector="Financial Services", debt_to_equity=900.0)
    _, _, factors = score_stock(bank, EMPTY_PROFILE, PRESETS["results"])
    results = next(f for f in factors if f.key == "results")
    assert not any("Schuld" in text for _, text in results.reasons)


def test_profile_shares():
    positions = [
        SimpleNamespace(value_eur=75.0, sector="Tech", country="NL", ticker="A", isin="I1"),
        SimpleNamespace(value_eur=25.0, sector="Energy", country="US", ticker="B", isin="I2"),
        SimpleNamespace(value_eur=None, sector="Energy", country="US", ticker="C", isin="I3"),
    ]
    profile = portfolio_profile(positions)
    assert profile["sectors"] == {"Tech": 75.0, "Energy": 25.0}
    assert profile["held_tickers"] == {"A", "B", "C"}


class ScreenProvider(FakeProvider):
    def __init__(self, tickers):
        super().__init__()
        for n, ticker in enumerate(tickers):
            self.series[ticker] = synthetic_prices(seed=50 + n)
        self.limit_after = None
        self.fundamental_calls = 0

    def fundamentals(self, ticker):
        self.fundamental_calls += 1
        if self.limit_after is not None and self.fundamental_calls > self.limit_after:
            raise RuntimeError("Too Many Requests. Rate limited.")
        if ticker.startswith("BADTICKER"):
            return {}
        return super().fundamentals(ticker)


def test_batch_refresh_takes_oldest_first_and_continues(factory, session):
    tickers = ["A.AS", "B.AS", "C.AS", "D.AS"]
    add_manual_tickers(session, tickers)
    session.commit()
    provider = ScreenProvider(tickers)
    status = refresh_batch(factory, provider, batch=2)
    assert status["done"] == 2
    session.expire_all()
    assert screener_counts(session)["with_data"] == 2
    status = refresh_batch(factory, provider, batch=2)
    assert status["done"] == 2
    session.expire_all()
    assert screener_counts(session)["with_data"] == 4
    assert session.query(Price).filter_by(ticker="D.AS").count() > 0


def test_batch_stops_on_rate_limit_and_keeps_progress(factory, session):
    tickers = ["A.AS", "B.AS", "C.AS"]
    add_manual_tickers(session, tickers)
    session.commit()
    provider = ScreenProvider(tickers)
    provider.limit_after = 1
    status = refresh_batch(factory, provider, batch=3)
    assert status["stopped_early"] is True
    assert status["done"] == 1
    session.expire_all()
    # The stocks it didn't reach have no error and are next in line.
    remaining = session.query(ScreenerStock).filter(ScreenerStock.last_refresh.is_(None)).count()
    assert remaining == 2
    assert session.query(ScreenerStock).filter(ScreenerStock.refresh_error.is_not(None)).count() == 0


def test_bad_ticker_is_reported_and_does_not_block(factory, session):
    add_manual_tickers(session, ["BADTICKER.XX", "A.AS"])
    session.commit()
    status = refresh_batch(factory, ScreenProvider(["A.AS"]), batch=5)
    assert status["failed"] == 1
    assert status["done"] == 1
    session.expire_all()
    assert session.get(ScreenerStock, "BADTICKER.XX").refresh_error


def test_seed_keeps_manual_changes(session):
    assert seed_universe(session) > 500
    first = session.query(ScreenerStock).first()
    first.enabled = False
    session.flush()
    assert seed_universe(session) == 0
    assert session.get(ScreenerStock, first.ticker).enabled is False


def test_universe_file_is_sane(session):
    seed_universe(session)
    tickers = [s.ticker for s in session.query(ScreenerStock).all()]
    assert "ASML.AS" in tickers
    assert "MSFT" in tickers
    assert all(" " not in t for t in tickers)
    assert isinstance(pd.Series(tickers).is_unique, bool) and pd.Series(tickers).is_unique
