"""Every page, in the empty state and with data, through the real app."""
from __future__ import annotations

import dataclasses
import time

import pytest
from fastapi.testclient import TestClient

from app.analysis.service import clear_cache
from app.config import load_config
from app.main import create_app
from tests.conftest import FakeProvider, ISIN_NL, make_account_csv, make_transactions_csv

PAGES = ["/", "/signals", "/dividends", "/backtest", "/import", "/settings", "/login"]


def _client(tmp_path, password=""):
    clear_cache()
    (tmp_path / "data").mkdir(exist_ok=True)
    base = load_config()
    config = dataclasses.replace(base, data_dir=tmp_path / "data", password=password, scheduler_enabled=False)
    config.upload_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(config, FakeProvider()))


def _wait_for_refresh(client):
    for _ in range(200):
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
        yield c


@pytest.fixture()
def loaded(client):
    _import(client, make_transactions_csv(), "Transactions.csv")
    _import(client, make_account_csv(), "Account.csv")
    _wait_for_refresh(client)
    clear_cache()
    return client


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
        preview = c.post("/import", files={"file": ("t.csv", make_transactions_csv(), "text/csv")})
        token = preview.text.split('name="token" value="')[1].split('"')[0]
        assert list((tmp_path / "data" / "uploads").iterdir())
        c.post("/import/cancel", data={"token": token})
        assert not list((tmp_path / "data" / "uploads").iterdir())


def test_confirm_rejects_path_traversal(client):
    response = client.post("/import/confirm", data={"token": "../../secret"})
    assert "verlopen" in response.text


def test_wrong_file_shows_a_clear_message(client):
    response = client.post("/import", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert "geen DEGIRO-export" in response.text


def test_uploaded_text_is_escaped(client):
    raw = ("Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n"
           '01-01-2025,09:00,01-01-2025,X,,<script>alert(1)</script>,,EUR,"1,00",EUR,"1,00",\n').encode()
    response = client.post("/import", files={"file": ("x.csv", raw, "text/csv")})
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


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


def test_login_required_when_password_set(tmp_path):
    with _client(tmp_path, password="testwachtwoord") as c:
        assert c.get("/", follow_redirects=False).status_code == 303
        assert c.get("/healthz").status_code == 200
        assert "Onjuist" in c.post("/login", data={"password": "fout"}).text
        assert c.get("/", follow_redirects=False).status_code == 303
        c.post("/login", data={"password": "testwachtwoord"})
        assert c.get("/", follow_redirects=False).status_code == 200
        c.post("/logout")
        assert c.get("/", follow_redirects=False).status_code == 303


def test_form_post_from_another_site_is_rejected(client):
    response = client.post("/refresh", headers={"origin": "https://evil.example"})
    assert response.status_code == 403
