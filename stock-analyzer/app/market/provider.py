"""The interface every market data source implements.

To add a paid feed, write one class with these methods and register it in `get_provider`.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass
class SymbolMatch:
    ticker: str
    name: str
    exchange: str | None = None
    quote_type: str | None = None


class MarketDataProvider(Protocol):
    def resolve_isin(self, isin: str, name: str, exchange: str | None) -> SymbolMatch | None:
        """Find the ticker for an ISIN, preferring the exchange DEGIRO reports."""

    def price_history(self, ticker: str, start: dt.date | None) -> pd.DataFrame:
        """Daily data indexed by date, columns: close, adj_close, volume.

        `start=None` means all available history.
        """

    def dividends(self, ticker: str) -> pd.Series:
        """Dividend per share indexed by ex-date."""

    def fundamentals(self, ticker: str) -> dict:
        """Keys used (all optional): name, currency, quote_type, sector, country,
        trailing_pe, payout_ratio, profit_margin, debt_to_equity,
        next_ex_date (ISO), next_pay_date (ISO).
        """

    def fx_history(self, currency: str, start: dt.date | None) -> pd.Series:
        """EUR value of one unit of `currency`, indexed by date."""


def get_provider(name: str) -> MarketDataProvider:
    if name == "yfinance":
        from app.market.yfinance_provider import YFinanceProvider

        return YFinanceProvider()
    raise ValueError(f"Unknown market data provider: {name}")
