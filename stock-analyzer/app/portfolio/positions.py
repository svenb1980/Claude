"""Current positions and profit, built up from the imported transactions.

Cost basis uses the average cost method in EUR, including transaction costs.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccountEntry, FxRate, Price, Product, Transaction

QTY_EPSILON = 1e-6

# Yahoo quotes some markets in minor units, such as pence on the London exchange.
MINOR_UNITS = {"GBp": ("GBP", 0.01), "GBX": ("GBP", 0.01), "ILA": ("ILS", 0.01), "ZAc": ("ZAR", 0.01)}


def normalise_currency(currency: str | None) -> tuple[str | None, float]:
    """Return (major currency, factor to multiply a quoted price by)."""
    if currency in MINOR_UNITS:
        return MINOR_UNITS[currency]
    return (currency.upper() if currency else None), 1.0


@dataclass
class Lot:
    """Running state for one ISIN while replaying its transactions."""

    isin: str
    product: str = ""
    quantity: float = 0.0
    cost_eur: float = 0.0
    realised_eur: float = 0.0
    fees_eur: float = 0.0
    first_buy: dt.date | None = None
    warnings: list[str] = field(default_factory=list)


def _cash_flow_eur(tx) -> float | None:
    """Cash effect of a transaction in EUR: negative for a buy, positive for a sell."""
    if tx.total_eur is not None:
        return tx.total_eur
    if tx.value_eur is not None:
        return tx.value_eur - (tx.fees_eur or 0.0)
    return None


def replay_transactions(transactions: Iterable) -> dict[str, Lot]:
    """Replay transactions in date order and return the state per ISIN."""
    lots: dict[str, Lot] = {}
    for tx in sorted(transactions, key=lambda t: (t.date, t.time or "")):
        lot = lots.setdefault(tx.isin, Lot(isin=tx.isin))
        lot.product = tx.product or lot.product
        lot.fees_eur += tx.fees_eur or 0.0
        cash = _cash_flow_eur(tx)
        if tx.quantity > 0:
            if lot.quantity <= QTY_EPSILON:
                lot.first_buy = tx.date
            if cash is None:
                lot.warnings.append(f"Geen EUR-bedrag voor aankoop op {tx.date:%d-%m-%Y}")
                cash = 0.0
            lot.quantity += tx.quantity
            lot.cost_eur += -cash
        elif tx.quantity < 0:
            sold = -tx.quantity
            if sold > lot.quantity + QTY_EPSILON:
                # Usually an export that starts after the original purchase.
                lot.warnings.append(
                    f"Verkoop op {tx.date:%d-%m-%Y} van {sold:g} stuks, maar slechts "
                    f"{lot.quantity:g} in bezit: de export is mogelijk onvolledig"
                )
                sold = lot.quantity
            average = lot.cost_eur / lot.quantity if lot.quantity > QTY_EPSILON else 0.0
            cost_of_sold = average * sold
            if cash is not None and sold > 0:
                proceeds = cash * (sold / -tx.quantity)
                lot.realised_eur += proceeds - cost_of_sold
            lot.quantity -= sold
            lot.cost_eur -= cost_of_sold
            if lot.quantity <= QTY_EPSILON:
                lot.quantity = 0.0
                lot.cost_eur = 0.0
    return lots


def latest_fx(session: Session, currency: str | None, on: dt.date | None = None) -> float | None:
    """EUR value of one unit of currency. On a date, uses the last known rate before it."""
    if currency is None:
        return None
    if currency == "EUR":
        return 1.0
    query = select(FxRate.eur_per_unit).where(FxRate.currency == currency)
    if on is not None:
        query = query.where(FxRate.date <= on)
    return session.scalars(query.order_by(FxRate.date.desc()).limit(1)).first()


@dataclass
class Position:
    isin: str
    name: str
    ticker: str | None
    quantity: float
    cost_eur: float
    average_cost_eur: float
    price: float | None
    price_date: dt.date | None
    currency: str | None
    value_eur: float | None
    unrealised_eur: float | None
    unrealised_pct: float | None
    realised_eur: float
    dividends_eur: float
    weight_pct: float | None
    sector: str | None
    country: str | None
    quote_type: str | None
    first_buy: dt.date | None
    warnings: list[str]
    refresh_error: str | None


@dataclass
class PortfolioSummary:
    positions: list[Position]
    value_eur: float
    cost_eur: float
    unrealised_eur: float
    realised_eur: float
    dividends_eur: float
    fees_eur: float
    unpriced: int
    warnings: list[str]


def _latest_price(session: Session, ticker: str) -> tuple[float, dt.date] | None:
    row = session.execute(
        select(Price.close, Price.date)
        .where(Price.ticker == ticker)
        .order_by(Price.date.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def dividends_received_eur(session: Session) -> dict[str, float]:
    """Net dividends received per ISIN, in EUR."""
    from app.dividends.calendar import received_dividends

    totals: dict[str, float] = {}
    for item in received_dividends(session):
        if item.net_eur is not None:
            totals[item.isin] = totals.get(item.isin, 0.0) + item.net_eur
    return totals


def build_portfolio(session: Session) -> PortfolioSummary:
    lots = replay_transactions(session.scalars(select(Transaction)).all())
    products = {p.isin: p for p in session.scalars(select(Product)).all()}
    dividends = dividends_received_eur(session)
    positions: list[Position] = []
    warnings: list[str] = []
    fees_eur = sum(lot.fees_eur for lot in lots.values())
    realised = sum(lot.realised_eur for lot in lots.values())

    for lot in lots.values():
        for warning in lot.warnings:
            warnings.append(f"{lot.product or lot.isin}: {warning}")
        if lot.quantity <= QTY_EPSILON:
            continue
        product = products.get(lot.isin)
        ticker = product.ticker if product else None
        price, price_date, value_eur = None, None, None
        currency = product.currency if product else None
        if ticker:
            latest = _latest_price(session, ticker)
            if latest:
                price, price_date = latest
                major, factor = normalise_currency(currency)
                fx = latest_fx(session, major)
                if fx is not None:
                    value_eur = lot.quantity * price * factor * fx
        unrealised = value_eur - lot.cost_eur if value_eur is not None else None
        positions.append(
            Position(
                isin=lot.isin,
                name=(product.name if product else "") or lot.product or lot.isin,
                ticker=ticker,
                quantity=lot.quantity,
                cost_eur=lot.cost_eur,
                average_cost_eur=lot.cost_eur / lot.quantity,
                price=price,
                price_date=price_date,
                currency=currency,
                value_eur=value_eur,
                unrealised_eur=unrealised,
                unrealised_pct=(unrealised / lot.cost_eur * 100) if unrealised is not None and lot.cost_eur else None,
                realised_eur=lot.realised_eur,
                dividends_eur=dividends.get(lot.isin, 0.0),
                weight_pct=None,
                sector=product.sector if product else None,
                country=product.country if product else None,
                quote_type=product.quote_type if product else None,
                first_buy=lot.first_buy,
                warnings=lot.warnings,
                refresh_error=product.refresh_error if product else None,
            )
        )

    total_value = sum(p.value_eur for p in positions if p.value_eur is not None)
    for position in positions:
        if position.value_eur is not None and total_value > 0:
            position.weight_pct = position.value_eur / total_value * 100
    positions.sort(key=lambda p: (p.value_eur is None, -(p.value_eur or 0.0), p.name))

    return PortfolioSummary(
        positions=positions,
        value_eur=total_value,
        cost_eur=sum(p.cost_eur for p in positions),
        unrealised_eur=sum(p.unrealised_eur for p in positions if p.unrealised_eur is not None),
        realised_eur=realised,
        dividends_eur=sum(dividends.values()),
        fees_eur=fees_eur,
        unpriced=sum(1 for p in positions if p.value_eur is None),
        warnings=warnings,
    )


def import_status(session: Session) -> dict:
    def _range(model):
        return session.execute(select(func.count(), func.min(model.date), func.max(model.date)).select_from(model)).one()

    tx_count, tx_first, tx_last = _range(Transaction)
    ac_count, ac_first, ac_last = _range(AccountEntry)
    return {
        "tx_count": tx_count, "tx_first": tx_first, "tx_last": tx_last,
        "ac_count": ac_count, "ac_first": ac_first, "ac_last": ac_last,
    }
