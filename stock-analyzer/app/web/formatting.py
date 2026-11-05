"""Dutch number and date formatting for the templates."""
from __future__ import annotations

import datetime as dt

DASH = "–"


def _dutch(value: float, decimals: int) -> str:
    text = f"{value:,.{decimals}f}"
    return text.replace(",", " TMP").replace(".", ",").replace(" TMP", ".")


def number(value, decimals: int = 2) -> str:
    return DASH if value is None else _dutch(float(value), decimals)


def eur(value, decimals: int = 2) -> str:
    if value is None:
        return DASH
    amount = float(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}€ {_dutch(abs(amount), decimals)}"


def signed_eur(value) -> str:
    if value is None:
        return DASH
    return ("+" if float(value) > 0 else "") + eur(value)


def pct(value, decimals: int = 1) -> str:
    """Format a value that is already in percent."""
    return DASH if value is None else f"{_dutch(float(value), decimals)}%"


def ratio_pct(value, decimals: int = 1) -> str:
    """Format a fraction such as 0.12 as a percentage."""
    return DASH if value is None else pct(float(value) * 100, decimals)


def signed_ratio_pct(value, decimals: int = 1) -> str:
    if value is None:
        return DASH
    return ("+" if float(value) > 0 else "") + ratio_pct(value, decimals)


def date(value) -> str:
    if not value:
        return DASH
    if isinstance(value, str):
        value = dt.date.fromisoformat(value[:10])
    return value.strftime("%d-%m-%Y")


def datetime(value) -> str:
    if not value:
        return DASH
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value)
    return value.strftime("%d-%m-%Y %H:%M")


def quantity(value) -> str:
    if value is None:
        return DASH
    return number(value, 0) if float(value).is_integer() else number(value, 4)


FILTERS = {
    "number": number, "eur": eur, "signed_eur": signed_eur, "pct": pct, "ratio_pct": ratio_pct,
    "signed_ratio_pct": signed_ratio_pct, "nldate": date, "nldatetime": datetime, "quantity": quantity,
}
