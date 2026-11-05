"""Database tables.

Market data (products, prices, dividends, FX, screener) is shared by all users.
Everything derived from a person's exports hangs off a portfolio, and every query
for it filters on that portfolio.
"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Raised when the password changes, which logs out existing sessions.
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class Product(Base):
    """A security known from an export, keyed by ISIN. Shared market data."""

    __tablename__ = "products"

    isin: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ticker_source: Mapped[str] = mapped_column(String(8), default="auto")  # auto | manual
    quote_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(80), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fundamentals_json: Mapped[str] = mapped_column(Text, default="{}")
    last_refresh: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def fundamentals(self) -> dict:
        return json.loads(self.fundamentals_json or "{}")


class Transaction(Base):
    """A buy or sell from the Transactions export."""

    __tablename__ = "transactions"

    portfolio_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    row_hash: Mapped[str] = mapped_column(String(40), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    time: Mapped[str] = mapped_column(String(8), default="")
    isin: Mapped[str] = mapped_column(String(12), index=True)
    product: Mapped[str] = mapped_column(String(200), default="")
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quantity: Mapped[float] = mapped_column(Float)  # negative for a sell
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    value_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees_eur: Mapped[float] = mapped_column(Float, default=0.0)
    total_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AccountEntry(Base):
    """A cash movement from the Account Statement export."""

    __tablename__ = "account_entries"

    portfolio_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    row_hash: Mapped[str] = mapped_column(String(40), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    value_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    product: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    kind: Mapped[str] = mapped_column(String(16))  # see importers.degiro_csv.classify
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx: Mapped[float | None] = mapped_column(Float, nullable=True)


class Price(Base):
    __tablename__ = "prices"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)


class DividendHistory(Base):
    """Dividend per share by ex-date, in the ticker's quote currency."""

    __tablename__ = "dividend_history"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    ex_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    amount: Mapped[float] = mapped_column(Float)


class FxRate(Base):
    """Value of one unit of `currency` in EUR."""

    __tablename__ = "fx_rates"

    currency: Mapped[str] = mapped_column(String(8), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    eur_per_unit: Mapped[float] = mapped_column(Float)


class ScreenerStock(Base):
    """A stock the screener searches, with its latest calculated inputs."""

    __tablename__ = "screener_stocks"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    indices: Mapped[str] = mapped_column(String(200), default="")  # comma separated
    source: Mapped[str] = mapped_column(String(8), default="list")  # list | manual
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sector: Mapped[str | None] = mapped_column(String(80), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quote_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    data_json: Mapped[str] = mapped_column(Text, default="{}")  # metrics + fundamentals
    last_refresh: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base):
    """Small JSON values. Per-user values use a key such as `analysis:3`."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
