"""Every page, in the empty state and with data, through the real app."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.analysis.service import clear_cache
from app.config import load_config
from app.db import session_scope
from app.main import create_app
from app.models import Portfolio, ScreenerStock, User
from tests.conftest import FakeProvider, ISIN_NL, make_account_csv, make_transactions_csv

PAGES = ["/", "/signals", "/screener", "/dividends", "/backtest", "/import", "/settings", "/account"]
ADMIN = ("beheerder", "testwachtwoord-admin")
OTHER = ("bob", "testwachtwoord-bob")


class IntradayProvider(FakeProvider):
    def intraday(self, ticker, interval="5m", period="60d"):
        index, values = [], []
        for offset, day in enumerate(pd.bdate_range("2026-10-20", periods=11)):
            session = pd.date_range(day + pd.Timedelta(hours=9), periods=78, freq="5min", tz="Europe/Amsterdam")
            index.extend(session)
            values.extend(100 + offset * 0.1 + np.sin(np.linspace(0, 6, 78)))
        close = np.array(values)
        return pd.DataFrame({"open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 10.0},
                            index=pd.DatetimeIndex(index))


def _client(tmp_path, provider=None):
    clear_cache()
    (tmp_path / "data").mkdir(exist_ok=True)
    base = load_config()
    config = dataclasses.replace(base, data_dir=tmp_path / "data", scheduler_enabled=False)
    config.upload_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(config, provider or IntradayProvider(), seed=False))


def _setup_admin(client):
    return client.post("/setup", data={"username": ADMIN[0], "password": ADMIN[1]})


def _login(client, credentials):
    return client.post("/login", data={"username": credentials[0], "password": credentials[1]})


def _wait_for_refresh(client):
    for _ in range(300):
        response = client.get("/")
        if "wordt vernieuwd" not in response.text and "Laatst vernieuwd" in response.text:
            return
        time.sleep(0.05)
    raise AssertionError("refresh did not finish")


def _import(client, raw, name):
    preview = client.post("/import", files={"file": (name, raw, "text/csv")})
    assert preview.status_code == 200
    token = preview.text.split('name="token" value="')[1].split('"')[0]
    return preview, client.post("/import/confirm", data={"token": token})


@pytest.fixture()
def client(tmp_path):
    with _client(tmp_path) as c:
        _setup_admin(c)
        yield c


@pytest.fixture()
def loaded(client):
    _import(client, make_transactions_csv(), "Transactions.csv")
    _import(client, make_account_csv(), "Account.csv")
    _wait_for_refresh(client)
    clear_cache()
    return client


def _add_screener_stock(client, ticker="NEW.AS"):
    factory = client.app.state.session_factory
    data = {
        "metrics": {"pays_dividend": True, "yield": 0.04, "dividend_streak": 5, "price_vs_sma200": 0.1, "sma50_vs_sma200": 0.05,
                    "slope_12m": 0.2, "r3": 0.05, "r6": 0.1, "r12": 0.2, "rsi": 55, "vol_1y": 0.2, "max_dd_5y": -0.2,
                    "sharpe_3y": 1.0, "beta_3y": 0.9, "turnover_eur_m": 30.0, "last_date": "2026-11-03"},
        "fundamentals": {"sector": "Healthcare", "country": "Netherlands", "revenue_growth": 0.1, "earnings_growth": 0.2,
                         "return_on_equity": 0.2, "profit_margin": 0.2, "debt_to_equity": 40.0, "trailing_pe": 14.0,
                         "forward_pe": 12.0, "price_to_book": 2.0, "payout_ratio": 0.4, "spread_pct": 0.05},
    }
    with session_scope(factory) as session:
        session.add(ScreenerStock(ticker=ticker, name="Nieuw Bedrijf NV", data_json=json.dumps(data), sector="Healthcare",
                                  country="Netherlands", last_refresh=dt.datetime(2026, 11, 3)))


# --- First run and login --------------------------------------------------

def test_first_visit_goes_to_setup(tmp_path):
    with _client(tmp_path) as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/setup"
        assert c.get("/healthz").status_code == 200
        response = c.post("/setup", data={"username": "x", "password": "kort"})
        assert "gebruikersnaam" in response.text.lower()
        assert _setup_admin(c).status_code == 200
        assert c.get("/", follow_redirects=False).status_code == 200


def test_setup_is_closed_once_an_account_exists(tmp_path):
    with _client(tmp_path) as c:
        _setup_admin(c)
        c.post("/logout")
        c.post("/setup", data={"username": "aanvaller", "password": "aanvaller-wachtwoord"})
        assert "Onjuiste" in _login(c, ("aanvaller", "aanvaller-wachtwoord")).text


def test_pages_require_login(tmp_path):
    with _client(tmp_path) as c:
        _setup_admin(c)
        c.post("/logout")
        for path in PAGES + [f"/stocks/{ISIN_NL}", "/api/intraday/ACME.AS"]:
            response = c.get(path, follow_redirects=False)
            assert response.status_code == 303 and response.headers["location"] == "/login", path
        assert c.post("/refresh", follow_redirects=False).headers["location"] == "/login"


def test_wrong_password_and_lockout(tmp_path):
    with _client(tmp_path) as c:
        _setup_admin(c)
        c.post("/logout")
        for _ in range(5):
            assert "Onjuiste" in _login(c, (ADMIN[0], "fout-wachtwoord")).text
        assert "Te veel" in _login(c, ADMIN).text
        from app import auth

        auth.clear_failures(ADMIN[0])
        _login(c, ADMIN)
        assert c.get("/", follow_redirects=False).status_code == 200


def test_form_post_from_another_site_is_rejected(client):
    assert client.post("/refresh", headers={"origin": "https://evil.example"}).status_code == 403


def test_password_change_logs_out_other_sessions(tmp_path):
    with _client(tmp_path) as c:
        _setup_admin(c)
        other = TestClient(c.app)
        _login(other, ADMIN)
        assert other.get("/", follow_redirects=False).status_code == 200
        c.post("/account/password", data={"current": ADMIN[1], "new": "nieuw-wachtwoord-123"})
        assert c.get("/", follow_redirects=False).status_code == 200
        assert other.get("/", follow_redirects=False).status_code == 303


# --- Pages ----------------------------------------------------------------

@pytest.mark.parametrize("path", PAGES)
def test_pages_render_when_empty(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "Geen financieel advies" in response.text


@pytest.mark.parametrize("path", PAGES + [f"/stocks/{ISIN_NL}"])
def test_pages_render_with_data(loaded, path):
    response = loaded.get(path)
    assert response.status_code == 200, response.text[:500]


def test_import_preview_saves_nothing_until_confirmed(client):
    preview = client.post("/import", files={"file": ("t.csv", make_transactions_csv(), "text/csv")})
    assert "Nieuw" in preview.text
    assert "Nog niets geïmporteerd" in preview.text
    assert "ACME" not in client.get("/").text


def test_cancel_removes_the_uploaded_file(tmp_path):
    with _client(tmp_path) as c:
        _setup_admin(c)
        preview = c.post("/import", files={"file": ("t.csv", make_transactions_csv(), "text/csv")})
        token = preview.text.split('name="token" value="')[1].split('"')[0]
        assert list((tmp_path / "data" / "uploads").iterdir())
        c.post("/import/cancel", data={"token": token})
        assert not list((tmp_path / "data" / "uploads").iterdir())


def test_confirm_rejects_path_traversal(client):
    assert "verlopen" in client.post("/import/confirm", data={"token": "../../secret"}).text


def test_wrong_file_shows_a_clear_message(client):
    assert "geen DEGIRO-export" in client.post("/import", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}).text


def test_uploaded_text_is_escaped(client):
    raw = ("Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n"
           '01-01-2025,09:00,01-01-2025,X,,<script>alert(1)</script>,,EUR,"1,00",EUR,"1,00",\n').encode()
    response = client.post("/import", files={"file": ("x.csv", raw, "text/csv")})
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_dashboard_compares_with_the_market(loaded):
    text = loaded.get("/").text
    assert "Mijn aandelen tegenover de markt" in text
    assert "Portefeuille" in text
    data = loaded.get("/api/market-comparison").json()
    assert data["subjects"][0]["label"] == "Portefeuille"
    assert data["points"]
    json.dumps(data, allow_nan=False)


def test_market_comparison_is_private(two_users):
    admin, bob = two_users
    clear_cache()
    assert "error" not in admin.get("/api/market-comparison").json()
    data = bob.get("/api/market-comparison").json()
    assert "error" in data
    assert "ACME" not in json.dumps(data)


def test_dashboard_shows_positions_and_signals(loaded):
    text = loaded.get("/").text
    assert "ACME NV" in text and "US CORP" in text
    assert "badge-" in text
    detail = loaded.get(f"/stocks/{ISIN_NL}").text
    assert "Opbouw van de score" in detail
    assert "200-daags" in detail


def test_dividend_calendar_month_navigation(loaded):
    text = loaded.get("/dividends?year=2025&month=5").text
    assert "mei 2025" in text
    assert "ACME NV" in text
    assert "/dividends?year=2025&amp;month=6" in text
    assert loaded.get("/dividends?year=2025&month=99").status_code == 200


def test_settings_change_applies_and_validates(loaded):
    form = {f"weight_{k}": "10" for k in ("trend", "momentum", "risk", "valuation", "quality", "fit")}
    form.update(sell_below="40", buy_from="60", max_position_pct="20", min_confidence_pct="50",
                risk_free_pct="2", benchmark="IWDA.AS")
    assert "Opgeslagen" in loaded.post("/settings", data=form).text
    assert "Verkopen onder 40" in loaded.get("/signals").text

    form.update(sell_below="70")
    assert "Ongeldige invoer" in loaded.post("/settings", data=form).text
    assert "Verkopen onder 40" in loaded.get("/signals").text


def test_backtest_runs_to_completion(loaded):
    loaded.post("/backtest/run")
    for _ in range(600):
        text = loaded.get("/backtest").text
        if "Backtest loopt" not in text:
            break
        time.sleep(0.05)
    assert "Totaal rendement" in text
    assert "Overlevingsbias" in text


# --- Sell levels ----------------------------------------------------------

def test_stock_page_has_sell_lines_with_evidence(loaded):
    text = loaded.get(f"/stocks/{ISIN_NL}").text
    assert "Verkoopniveaus" in text
    assert "Stop" in text
    assert "keer" in text
    assert "lopen ongeveer 15 minuten" in text


def test_intraday_api(loaded):
    data = loaded.get("/api/intraday/ACME.AS").json()
    assert data["chart"]["levels"]
    keys = {row["key"] for row in data["rows"]}
    assert {"r1", "r2", "s1"} <= keys
    assert any("kosten" in note for note in data["notes"])
    json.dumps(data, allow_nan=False)


def test_intraday_refuses_unknown_tickers(client):
    assert client.get("/api/intraday/WHATEVER").status_code == 404
    assert client.get("/api/intraday/a%20b").status_code == 404


# --- Screener -------------------------------------------------------------

def test_screener_shows_candidates_with_reasons(loaded):
    _add_screener_stock(loaded)
    text = loaded.get("/screener").text
    assert "Nieuw Bedrijf NV" in text
    assert "niet getoetst" in text
    detail = loaded.get("/market/NEW.AS").text
    assert "Opbouw van de score" in detail


@pytest.mark.parametrize("query", ["preset=dividend", "preset=onzin", "q=nieuw", "sector=Healthcare", "min_yield=3", "label=candidate", "min_yield=abc"])
def test_screener_filters(loaded, query):
    _add_screener_stock(loaded)
    response = loaded.get(f"/screener?{query}")
    assert response.status_code == 200
    if query in ("q=nieuw", "sector=Healthcare", "min_yield=3"):
        assert "Nieuw Bedrijf NV" in response.text


def test_screener_hides_stocks_you_hold(loaded):
    factory = loaded.app.state.session_factory
    _add_screener_stock(loaded, "ACME.AS")
    assert "Nieuw Bedrijf NV" not in loaded.get("/screener").text
    with session_scope(factory) as session:
        assert session.get(ScreenerStock, "ACME.AS") is not None


def test_unknown_market_page(client):
    assert "niet in de lijst" in client.get("/market/NOPE").text


# --- Separation between users ---------------------------------------------

@pytest.fixture()
def two_users(loaded):
    """The admin holds ACME and US CORP. Bob has an empty portfolio."""
    loaded.post("/users", data={"username": OTHER[0], "password": OTHER[1]})
    bob = TestClient(loaded.app)
    assert _login(bob, OTHER).status_code == 200
    return loaded, bob


def test_other_user_sees_none_of_your_data(two_users):
    admin, bob = two_users
    clear_cache()
    assert "ACME NV" in admin.get("/").text
    for path in ("/", "/signals", "/dividends", "/settings", "/import", "/backtest"):
        text = bob.get(path).text
        assert "ACME" not in text and "US CORP" not in text, path
    assert "ACME" not in bob.get(f"/stocks/{ISIN_NL}").text


def test_other_user_cannot_select_your_portfolio(two_users):
    admin, bob = two_users
    factory = admin.app.state.session_factory
    with session_scope(factory) as session:
        admin_id = session.query(User).filter_by(username=ADMIN[0]).one().id
        admin_portfolio = session.query(Portfolio).filter_by(user_id=admin_id).first().id
    bob.post("/portfolios/select", data={"portfolio_id": admin_portfolio})
    assert "ACME" not in bob.get("/").text
    bob.post(f"/portfolios/{admin_portfolio}/rename", data={"name": "gehackt"})
    assert bob.post(f"/portfolios/{admin_portfolio}/delete", data={"confirm_name": "Mijn portefeuille"}).status_code == 200
    with session_scope(factory) as session:
        portfolio = session.get(Portfolio, admin_portfolio)
        assert portfolio is not None and portfolio.name == "Mijn portefeuille"
    assert "ACME" in admin.get("/").text


def test_other_user_cannot_change_your_tickers(two_users):
    admin, bob = two_users
    bob.post("/settings/ticker", data={"isin": ISIN_NL, "ticker": "FOUT"})
    assert 'value="ACME.AS"' in admin.get("/settings").text


def test_upload_cannot_be_confirmed_by_another_user(two_users):
    admin, bob = two_users
    preview = admin.post("/import", files={"file": ("t.csv", make_transactions_csv(), "text/csv")})
    token = preview.text.split('name="token" value="')[1].split('"')[0]
    assert "verlopen" in bob.post("/import/confirm", data={"token": token}).text


def test_only_admin_manages_users_and_universe(two_users):
    admin, bob = two_users
    bob.post("/users", data={"username": "nieuw", "password": "testwachtwoord-x"})
    assert "Onjuiste" in _login(TestClient(admin.app), ("nieuw", "testwachtwoord-x")).text
    assert "Nieuwe gebruiker" not in bob.get("/account").text
    assert "Nieuwe gebruiker" in admin.get("/account").text
    factory = admin.app.state.session_factory
    bob.post("/settings/universe", data={"tickers": "HACK.AS"})
    with session_scope(factory) as session:
        assert session.get(ScreenerStock, "HACK.AS") is None
    admin.post("/settings/universe", data={"tickers": "goed.as, BETER.AS"})
    with session_scope(factory) as session:
        assert session.get(ScreenerStock, "GOED.AS") is not None
        assert session.get(ScreenerStock, "BETER.AS") is not None


def test_settings_are_per_user(two_users):
    admin, bob = two_users
    form = {f"weight_{k}": "10" for k in ("trend", "momentum", "risk", "valuation", "quality", "fit")}
    form.update(sell_below="40", buy_from="60", max_position_pct="20", min_confidence_pct="50", risk_free_pct="2", benchmark="IWDA.AS")
    bob.post("/settings", data=form)
    assert "Verkopen onder 40" in bob.get("/signals").text
    assert "Verkopen onder 35" in admin.get("/signals").text


# --- Several portfolios ---------------------------------------------------

def test_second_portfolio_is_separate_and_switchable(loaded):
    assert "ACME NV" in loaded.get("/").text
    loaded.post("/portfolios", data={"name": "Partner"})
    assert "ACME NV" not in loaded.get("/").text
    assert "Importeren in portefeuille: Partner" in loaded.get("/import").text
    factory = loaded.app.state.session_factory
    with session_scope(factory) as session:
        first = session.query(Portfolio).filter_by(name="Mijn portefeuille").one().id
    loaded.post("/portfolios/select", data={"portfolio_id": first})
    assert "ACME NV" in loaded.get("/").text


def test_portfolio_delete_needs_the_exact_name(loaded):
    loaded.post("/portfolios", data={"name": "Weg"})
    factory = loaded.app.state.session_factory
    with session_scope(factory) as session:
        target = session.query(Portfolio).filter_by(name="Weg").one().id
    assert "niets verwijderd" in loaded.post(f"/portfolios/{target}/delete", data={"confirm_name": "weg?"}).text
    loaded.post(f"/portfolios/{target}/delete", data={"confirm_name": "Weg"})
    with session_scope(factory) as session:
        assert session.get(Portfolio, target) is None
    assert "ACME NV" in loaded.get("/").text


def test_last_portfolio_cannot_be_deleted(client):
    factory = client.app.state.session_factory
    with session_scope(factory) as session:
        only = session.query(Portfolio).first()
        only_id, name = only.id, only.name
    assert "laatste portefeuille" in client.post(f"/portfolios/{only_id}/delete", data={"confirm_name": name}).text
