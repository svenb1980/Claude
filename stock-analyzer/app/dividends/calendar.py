"""Dividends you received, and dividends you can expect.

Free data often has ex-dates but no payment date, so payment dates are estimated from
the delay between ex-date and your own past receipts for that stock. Each expected item
says what is announced and what is estimated.
"""
from __future__ import annotations

import calendar as cal
import datetime as dt
from dataclasses import dataclass
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountEntry, DividendHistory, Product, Transaction
from app.portfolio.positions import latest_fx, normalise_currency

DEFAULT_PAY_LAG_DAYS = 21
MAX_PAY_LAG_DAYS = 120
STOPPED_AFTER_DAYS = 548  # No dividend for 18 months: don't project any.


@dataclass
class ReceivedDividend:
    isin: str
    name: str
    date: dt.date
    currency: str | None
    gross: float
    tax: float
    net: float
    gross_eur: float | None
    tax_eur: float | None
    net_eur: float | None

    @property
    def tax_rate(self) -> float | None:
        return abs(self.tax) / self.gross if self.gross > 0 else None


@dataclass
class ExpectedDividend:
    isin: str
    name: str
    ticker: str
    ex_date: dt.date
    pay_date: dt.date
    pay_basis: str  # confirmed | history | default
    status: str  # confirmed | date_confirmed | estimated
    per_share: float
    currency: str | None
    quantity: float
    gross_eur: float | None
    net_eur: float | None


def _fx_from_statement(session: Session) -> dict[tuple[dt.date, str], float]:
    """Exchange rates DEGIRO actually used, as foreign currency per EUR."""
    rows = session.scalars(
        select(AccountEntry).where(AccountEntry.fx.is_not(None), AccountEntry.currency.is_not(None))
    ).all()
    return {(r.date, r.currency): r.fx for r in rows if r.currency != "EUR" and r.fx and r.fx > 0}


def _to_eur(session: Session, statement_fx: dict, date: dt.date, currency: str | None, amount: float) -> float | None:
    if currency == "EUR":
        return amount
    if currency is None:
        return None
    fx = statement_fx.get((date, currency))
    if fx:
        return amount / fx
    rate = latest_fx(session, currency, date)
    return amount * rate if rate is not None else None


def received_dividends(session: Session) -> list[ReceivedDividend]:
    entries = session.scalars(
        select(AccountEntry).where(AccountEntry.kind.in_(("dividend", "dividend_tax")), AccountEntry.isin.is_not(None))
    ).all()
    products = {p.isin: p for p in session.scalars(select(Product)).all()}
    statement_fx = _fx_from_statement(session)

    groups: dict[tuple[str, dt.date], dict] = {}
    for entry in entries:
        if entry.amount is None:
            continue
        group = groups.setdefault((entry.isin, entry.date), {
            "name": entry.product, "currency": entry.currency, "gross": 0.0, "tax": 0.0,
            "gross_eur": 0.0, "tax_eur": 0.0, "unconverted": False,
        })
        eur = _to_eur(session, statement_fx, entry.date, entry.currency, entry.amount)
        if eur is None:
            group["unconverted"] = True
        key = "gross" if entry.kind == "dividend" else "tax"
        group[key] += entry.amount
        if eur is not None:
            group[f"{key}_eur"] += eur

    received: list[ReceivedDividend] = []
    for (isin, date), g in groups.items():
        # A reversed and rebooked dividend can net out to nothing.
        if abs(g["gross"]) < 1e-9 and abs(g["tax"]) < 1e-9:
            continue
        product = products.get(isin)
        known = not g["unconverted"]
        received.append(ReceivedDividend(
            isin=isin,
            name=(product.name if product else "") or g["name"],
            date=date,
            currency=g["currency"],
            gross=g["gross"],
            tax=g["tax"],
            net=g["gross"] + g["tax"],
            gross_eur=g["gross_eur"] if known else None,
            tax_eur=g["tax_eur"] if known else None,
            net_eur=g["gross_eur"] + g["tax_eur"] if known else None,
        ))
    received.sort(key=lambda r: r.date, reverse=True)
    return received


def _pay_lag(ex_dates: list[dt.date], receipts: list[dt.date]) -> int | None:
    """Typical days between ex-date and receiving the money, for one stock."""
    lags = []
    for receipt in receipts:
        before = [d for d in ex_dates if d <= receipt]
        if before:
            lag = (receipt - max(before)).days
            if lag <= MAX_PAY_LAG_DAYS:
                lags.append(lag)
    return int(median(lags)) if lags else None


def _next_weekday(day: dt.date) -> dt.date:
    """Markets and payments don't run at weekends, so estimates move to Monday."""
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return day


def _project(
    history: list[tuple[dt.date, float]], occupied: list[dt.date], today: dt.date, horizon: dt.date
) -> list[tuple[dt.date, float]]:
    """Repeat the last year's pattern. Handles seasonal payers with a final and an interim."""
    if not history or (today - history[-1][0]).days > STOPPED_AFTER_DAYS:
        return []
    latest = [d for d, _ in history][-6:]
    gaps = [(b - a).days for a, b in zip(latest, latest[1:])]
    gap = median(gaps) if gaps else 365
    too_close = gap * 0.6  # Two payments closer than this are the same one in a new year.

    taken = list(occupied)
    recent = [item for item in history if (today - item[0]).days <= 400]
    projected: list[tuple[dt.date, float]] = []
    # Newest first, so the latest amount wins when two source dates land on one payment.
    for source, amount in sorted(recent, key=lambda x: x[0], reverse=True):
        target = source
        while target < today:
            try:
                target = target.replace(year=target.year + 1)
            except ValueError:  # 29 February
                target = target.replace(year=target.year + 1, day=28)
        target = _next_weekday(target)
        if target > horizon:
            continue
        if any(abs((target - other).days) < too_close for other in taken):
            continue
        taken.append(target)
        projected.append((target, amount))
    return sorted(projected)


def _quantity_before(transactions: list[Transaction], date: dt.date) -> float:
    """Shares held at the start of `date`. Buying on the ex-date earns no dividend."""
    return max(0.0, sum(t.quantity for t in transactions if t.date < date))


def expected_dividends(session: Session, today: dt.date | None = None, horizon_days: int = 365) -> list[ExpectedDividend]:
    today = today or dt.date.today()
    horizon = today + dt.timedelta(days=horizon_days)
    products = session.scalars(select(Product).where(Product.ticker.is_not(None))).all()
    all_tx = session.scalars(select(Transaction)).all()
    received = received_dividends(session)

    expected: list[ExpectedDividend] = []
    for product in products:
        transactions = [t for t in all_tx if t.isin == product.isin]
        if not transactions:
            continue
        rows = session.execute(
            select(DividendHistory.ex_date, DividendHistory.amount)
            .where(DividendHistory.ticker == product.ticker)
            .order_by(DividendHistory.ex_date)
        ).all()
        history = [(r[0], r[1]) for r in rows]
        past = [item for item in history if item[0] < today]
        ex_dates = [d for d, _ in history]
        own_receipts = [r for r in received if r.isin == product.isin]
        receipt_dates = [r.date for r in own_receipts]
        lag = _pay_lag(ex_dates, receipt_dates)
        rates = [r.tax_rate for r in own_receipts if r.tax_rate is not None]
        tax_rate = median(rates) if rates else None
        fundamentals = product.fundamentals
        major, factor = normalise_currency(product.currency)
        fx = latest_fx(session, major)
        latest_amount = past[-1][1] if past else None

        items: list[tuple[dt.date, float, str, dt.date | None]] = []

        # 1. Went ex recently and the money hasn't arrived yet.
        for ex_date, amount in past:
            waited = (today - ex_date).days
            if waited <= (lag if lag is not None else DEFAULT_PAY_LAG_DAYS) + 5 and not any(d >= ex_date for d in receipt_dates):
                items.append((ex_date, amount, "confirmed", None))
        # 2. A future ex-date that already has an amount.
        for ex_date, amount in history:
            if today <= ex_date <= horizon:
                items.append((ex_date, amount, "confirmed", None))

        # 3. An announced date with no amount yet.
        next_pay = _parse_iso(fundamentals.get("next_pay_date"))
        next_ex = _parse_iso(fundamentals.get("next_ex_date"))
        occupied = [d for d, _, _, _ in items] + [d for d, _ in past if (today - d).days <= 400]
        if next_ex and today <= next_ex <= horizon and latest_amount is not None and next_ex not in ex_dates:
            gap_guard = 20
            if not any(abs((next_ex - d).days) < gap_guard for d in occupied):
                items.append((next_ex, latest_amount, "date_confirmed", None))
                occupied.append(next_ex)

        # 4. The pattern of the past year.
        for ex_date, amount in _project(past, occupied, today, horizon):
            items.append((ex_date, amount, "estimated", None))

        for ex_date, per_share, status, _ in items:
            quantity = _quantity_before(transactions, ex_date)
            if quantity <= 0:
                continue
            if next_pay and ex_date <= next_pay <= ex_date + dt.timedelta(days=MAX_PAY_LAG_DAYS) and status != "estimated":
                pay_date, basis = next_pay, "confirmed"
            elif lag is not None:
                pay_date, basis = _next_weekday(ex_date + dt.timedelta(days=lag)), "history"
            else:
                pay_date, basis = _next_weekday(ex_date + dt.timedelta(days=DEFAULT_PAY_LAG_DAYS)), "default"
            if pay_date < today:
                pay_date = today
            gross = quantity * per_share * factor * fx if fx is not None else None
            net = gross * (1 - tax_rate) if gross is not None and tax_rate is not None else None
            expected.append(ExpectedDividend(
                isin=product.isin,
                name=product.name or product.isin,
                ticker=product.ticker,
                ex_date=ex_date,
                pay_date=pay_date,
                pay_basis=basis,
                status=status,
                per_share=per_share * factor,
                currency=major,
                quantity=quantity,
                gross_eur=gross,
                net_eur=net,
            ))
    expected.sort(key=lambda e: e.pay_date)
    return expected


def _parse_iso(value: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


@dataclass
class DayCell:
    date: dt.date | None
    received: list[ReceivedDividend]
    expected: list[ExpectedDividend]


def month_view(year: int, month: int, received: list[ReceivedDividend], expected: list[ExpectedDividend]) -> list[list[DayCell]]:
    weeks = []
    for week in cal.Calendar(firstweekday=0).monthdatescalendar(year, month):
        cells = []
        for day in week:
            if day.month != month:
                cells.append(DayCell(None, [], []))
            else:
                cells.append(DayCell(
                    day,
                    [r for r in received if r.date == day],
                    [e for e in expected if e.pay_date == day],
                ))
        weeks.append(cells)
    return weeks


def year_totals(year: int, received: list[ReceivedDividend], expected: list[ExpectedDividend]) -> dict:
    months = [{"month": m, "received": 0.0, "expected": 0.0} for m in range(1, 13)]
    totals = {"received_net": 0.0, "expected_gross": 0.0, "expected_net": 0.0, "net_unknown": 0}
    for item in received:
        if item.date.year == year and item.net_eur is not None:
            months[item.date.month - 1]["received"] += item.net_eur
            totals["received_net"] += item.net_eur
    for item in expected:
        if item.pay_date.year == year and item.gross_eur is not None:
            months[item.pay_date.month - 1]["expected"] += item.gross_eur
            totals["expected_gross"] += item.gross_eur
            if item.net_eur is not None:
                totals["expected_net"] += item.net_eur
            else:
                totals["net_unknown"] += 1
    # A total of zero would read as "no dividend" when the real answer is "not known".
    if totals["net_unknown"] and totals["expected_net"] == 0:
        totals["expected_net"] = None
    return {"months": months, **totals}
