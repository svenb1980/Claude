"""Shared test setup. All portfolio data here is made up."""
from __future__ import annotations

import datetime as dt
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="stock-analyzer-test-"))
os.environ["SCHEDULER_ENABLED"] = "0"

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from app.analysis.service import clear_cache
from app.db import make_engine, make_session_factory
from app.market.provider import SymbolMatch
from app.migrations import migrate

TX_HEADER = (
    "Datum,Tijd,Product,ISIN,Beurs,Uitvoeringsplaats,Aantal,Koers,,Lokale waarde,,Waarde,,"
    "Wisselkoers,Transactiekosten en/of,,Totaal,,Order ID\n"
)
ACCOUNT_HEADER = "Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n"

ISIN_NL = "NL0000000001"
ISIN_US = "US0000000002"
PID = 1


def tx_row(date, product, isin, exchange, qty, price, currency, value, fees, total):
    return (
        f'{date},10:00,{product},{isin},{exchange},XAMS,{qty},"{price}",{currency},"{value}",{currency},'
        f'"{value}",EUR,,"{fees}",EUR,"{total}",EUR,order-1\n'
    )


def acc_row(date, product, isin, description, currency, amount, fx=""):
    return f'{date},09:00,{date},{product},{isin},{description},"{fx}",{currency},"{amount}",EUR,"100,00",\n'


def make_transactions_csv() -> bytes:
    return (
        TX_HEADER
        + tx_row("10-01-2024", "ACME NV", ISIN_NL, "EAM", 10, "100,00", "EUR", "-1000,00", "-2,00", "-1002,00")
        + tx_row("10-02-2024", "ACME NV", ISIN_NL, "EAM", 10, "120,00", "EUR", "-1200,00", "-2,00", "-1202,00")
        + tx_row("10-03-2024", "ACME NV", ISIN_NL, "EAM", -5, "130,00", "EUR", "650,00", "-2,00", "648,00")
        + tx_row("15-01-2024", "US CORP", ISIN_US, "NDQ", 4, "200,00", "USD", "-800,00", "-1,00", "-737,00")
    ).encode("utf-8")


def make_account_csv() -> bytes:
    return (
        ACCOUNT_HEADER
        + acc_row("05-05-2025", "ACME NV", ISIN_NL, "Dividend", "EUR", "25,00")
        + acc_row("05-05-2025", "ACME NV", ISIN_NL, "Dividendbelasting", "EUR", "-3,75")
        + acc_row("20-06-2025", "US CORP", ISIN_US, "Dividend", "USD", "8,00")
        + acc_row("20-06-2025", "US CORP", ISIN_US, "Dividend Tax", "USD", "-1,20")
        + acc_row("20-06-2025", "", "", "Valuta Debitering", "USD", "-6,80", "1,0800")
        + acc_row("02-01-2024", "", "", "iDEAL storting", "EUR", "3000,00")
        + acc_row("03-01-2024", "", "", "Iets heel onbekends", "EUR", "1,00")
    ).encode("utf-8")


def synthetic_prices(days: int = 1500, start=100.0, drift=0.0004, vol=0.012, seed=1, end="2026-11-03") -> pd.Series:
    rng = np.random.default_rng(seed)
    values = start * np.exp(np.cumsum(rng.normal(drift, vol, days)))
    return pd.Series(values, index=pd.bdate_range(end=end, periods=days))


class FakeProvider:
    """Stands in for Yahoo. Records calls, so tests can check what gets fetched."""

    def __init__(self):
        self.history_calls: list[tuple] = []
        self.fail_for: set[str] = set()
        self.series = {
            "ACME.AS": synthetic_prices(seed=1),
            "USC": synthetic_prices(seed=2, start=200.0),
            "IWDA.AS": synthetic_prices(seed=3, start=60.0, drift=0.0003),
        }

    def resolve_isin(self, isin, name, exchange):
        return {
            ISIN_NL: SymbolMatch("ACME.AS", name, "AMS", "EQUITY"),
            ISIN_US: SymbolMatch("USC", name, "NMS", "EQUITY"),
        }.get(isin)

    def price_history(self, ticker, start):
        self.history_calls.append((ticker, start))
        if ticker in self.fail_for:
            raise RuntimeError("network down")
        series = self.series.get(ticker)
        if series is None:
            return pd.DataFrame(columns=["close", "adj_close", "volume", "high", "low"])
        if start is not None:
            series = series[series.index.date >= start]
        frame = pd.DataFrame(
            {"close": series.values, "adj_close": series.values, "volume": 1000.0,
             "high": series.values * 1.01, "low": series.values * 0.99},
            index=[d.date() for d in series.index],
        )
        return frame

    def dividends(self, ticker):
        if ticker in self.fail_for:
            raise RuntimeError("network down")
        if ticker == "ACME.AS":
            dates = [dt.date(y, 4, 25) for y in range(2021, 2027)]
            return pd.Series([1.0, 1.1, 1.2, 1.25, 1.25, 1.3], index=dates, dtype=float)
        if ticker == "USC":
            dates = [dt.date(2025, 3, 10), dt.date(2025, 6, 10), dt.date(2025, 9, 10),
                     dt.date(2025, 12, 10), dt.date(2026, 3, 10), dt.date(2026, 6, 10), dt.date(2026, 9, 10)]
            return pd.Series([2.0] * 7, index=dates, dtype=float)
        return pd.Series(dtype=float)

    def fundamentals(self, ticker):
        if ticker in self.fail_for:
            raise RuntimeError("network down")
        if ticker == "ACME.AS":
            return {"currency": "EUR", "quote_type": "EQUITY", "sector": "Technology", "country": "Netherlands",
                    "trailing_pe": 18.0, "payout_ratio": 0.4, "profit_margin": 0.15, "debt_to_equity": 60.0}
        return {"currency": "USD", "quote_type": "EQUITY", "sector": "Industrials", "country": "United States",
                "trailing_pe": 25.0, "payout_ratio": 0.5, "profit_margin": 0.1, "debt_to_equity": 120.0}

    def fx_history(self, currency, start):
        dates = [d.date() for d in pd.bdate_range(end="2026-11-03", periods=800)]
        return pd.Series([0.92] * len(dates), index=dates, dtype=float)


@pytest.fixture()
def factory(tmp_path):
    clear_cache()
    engine = make_engine(tmp_path / "test.db")
    migrate(engine)
    yield make_session_factory(engine)
    engine.dispose()
    clear_cache()


@pytest.fixture()
def session(factory) -> Session:
    s = factory()
    yield s
    s.close()


@pytest.fixture()
def provider():
    return FakeProvider()
