"""Parser for DEGIRO's Transactions and Account Statement CSV exports.

DEGIRO publishes no format specification, so this is written to tolerate variation:
Dutch or English headers, comma or semicolon separators, decimal commas, and currency
columns that sit in an unnamed column before or after the amount.

Nothing here touches the database. `parse_export` returns a result the user can review
first, and `app.importers.store` writes it after confirmation.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field

CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")
ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

# Header aliases, compared after lowercasing and trimming.
TX_COLUMNS = {
    "date": ("datum", "date"),
    "time": ("tijd", "time"),
    "product": ("product",),
    "isin": ("isin",),
    "exchange": ("beurs", "reference", "reference exchange", "referentiebeurs", "exchange"),
    "quantity": ("aantal", "quantity", "number"),
    "price": ("koers", "price"),
    "value": ("waarde", "value", "waarde eur", "value eur"),
    "fees": (
        "transactiekosten en/of",
        "transactiekosten",
        "transaction and/or third",
        "transaction costs",
        "transactiekosten en/of kosten van derden eur",
        "transaction and/or third party fees eur",
    ),
    "total": ("totaal", "total", "totaal eur", "total eur"),
    "order_id": ("order id", "order-id", "orderid"),
}
ACCOUNT_COLUMNS = {
    "date": ("datum", "date"),
    "time": ("tijd", "time"),
    "value_date": ("valutadatum", "value date"),
    "product": ("product",),
    "isin": ("isin",),
    "description": ("omschrijving", "description"),
    "fx": ("fx",),
    "amount": ("mutatie", "change"),
    "order_id": ("order id", "order-id", "orderid"),
}

# Checked in order: the first matching keyword decides. Tax goes before dividend,
# because "dividendbelasting" also contains "dividend".
KIND_RULES = (
    ("dividend_tax", ("dividendbelasting", "dividend tax", "bronbelasting", "withholding")),
    ("dividend", ("dividend", "capital return", "kapitaalsuitkering", "kapitaalteruggave")),
    ("fx", ("valuta creditering", "valuta debitering", "fx credit", "fx debit",
            "fx withdrawal", "fx deposit", "valutakosten", "autofx")),
    ("fee", ("kosten", "fee", "costs", "commission", "aansluitingskosten", "stamp")),
    ("cash", ("storting", "deposit", "withdrawal", "terugstorting", "overboeking",
              "ideal", "sofort", "flatex", "cash sweep", "geldmarkt", "money market",
              "rente", "interest")),
    ("trade", ("koop", "verkoop", "buy", "sell")),
)


class UnknownFormat(ValueError):
    """The file is not a recognisable DEGIRO export."""


@dataclass
class ParsedTransaction:
    row_hash: str
    date: dt.date
    time: str
    isin: str
    product: str
    exchange: str | None
    quantity: float
    price: float | None
    price_currency: str | None
    value_eur: float | None
    fees_eur: float
    total_eur: float | None
    order_id: str | None


@dataclass
class ParsedAccountEntry:
    row_hash: str
    date: dt.date
    value_date: dt.date | None
    isin: str | None
    product: str
    description: str
    kind: str
    currency: str | None
    amount: float | None
    fx: float | None


@dataclass
class BadRow:
    line: int
    reason: str
    text: str


@dataclass
class ParseResult:
    kind: str  # "transactions" | "account"
    transactions: list[ParsedTransaction] = field(default_factory=list)
    entries: list[ParsedAccountEntry] = field(default_factory=list)
    bad_rows: list[BadRow] = field(default_factory=list)
    unrecognised: list[ParsedAccountEntry] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.transactions) + len(self.entries)


def decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def parse_number(text: str | None) -> float | None:
    """Parse '1.234,56', '1,234.56', '-12,50' or '12.50'. Empty returns None."""
    if text is None:
        return None
    value = text.strip().replace(" ", "").replace(" ", "")
    if not value:
        return None
    has_comma, has_dot = "," in value, "." in value
    if has_comma and has_dot:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif has_comma:
        # DEGIRO writes decimals with a comma in its European exports.
        value = value.replace(",", "") if value.count(",") > 1 else value.replace(",", ".")
    elif value.count(".") > 1:
        value = value.replace(".", "")
    try:
        return float(value)
    except ValueError:
        return None


def parse_date(text: str | None) -> dt.date | None:
    if not text:
        return None
    value = text.strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def classify(description: str) -> str:
    """Sort an account statement line into a kind. Returns 'other' if unsure."""
    text = description.lower()
    for kind, keywords in KIND_RULES:
        if any(word in text for word in keywords):
            return kind
    return "other"


def _is_currency(text: str | None) -> bool:
    return bool(text and CURRENCY_RE.match(text.strip()))


def _find_columns(headers: list[str], aliases: dict) -> dict[str, int]:
    normalised = [h.strip().lower() for h in headers]
    found: dict[str, int] = {}
    for name, options in aliases.items():
        for index, header in enumerate(normalised):
            if header in options:
                found[name] = index
                break
    return found


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _amount_and_currency(row: list[str], index: int | None) -> tuple[float | None, str | None]:
    """Read an amount whose currency sits in the next column, in either order.

    Transactions use `amount, currency`. Account statements use `currency, amount`.
    """
    first, second = _cell(row, index), _cell(row, None if index is None else index + 1)
    if _is_currency(first):
        return parse_number(second), first.upper()
    if _is_currency(second):
        return parse_number(first), second.upper()
    return parse_number(first), None


def _make_hash(prefix: str, row: list[str], seen: Counter) -> str:
    """Stable row id, so importing an overlapping export adds no duplicates.

    Identical rows inside one file can be genuine (two equal fills), so each
    gets its occurrence number instead of being collapsed into one.
    """
    base = "\x1f".join(cell.strip() for cell in row)
    occurrence = seen[base]
    seen[base] += 1
    return hashlib.sha1(f"{prefix}\x1f{occurrence}\x1f{base}".encode()).hexdigest()


def _read_rows(raw: bytes) -> tuple[list[str], list[list[str]]]:
    text = decode_bytes(raw)
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if not rows:
        raise UnknownFormat("Het bestand is leeg.")
    return rows[0], rows[1:]


def parse_export(raw: bytes) -> ParseResult:
    """Detect which export this is and parse it."""
    headers, rows = _read_rows(raw)
    normalised = {h.strip().lower() for h in headers}
    if "isin" in normalised and normalised & {"aantal", "quantity", "number"}:
        return _parse_transactions(headers, rows)
    if normalised & {"omschrijving", "description"} and normalised & {"mutatie", "change"}:
        return _parse_account(headers, rows)
    raise UnknownFormat(
        "Dit lijkt geen DEGIRO-export. Verwacht: Transactions.csv of Account.csv. "
        f"Gevonden kolommen: {', '.join(h for h in headers if h.strip())[:300]}"
    )


def _parse_transactions(headers: list[str], rows: list[list[str]]) -> ParseResult:
    col = _find_columns(headers, TX_COLUMNS)
    result = ParseResult(kind="transactions")
    seen: Counter = Counter()
    for line, row in enumerate(rows, start=2):
        text = ",".join(row)[:200]
        date = parse_date(_cell(row, col.get("date")))
        isin = _cell(row, col.get("isin")).upper()
        quantity = parse_number(_cell(row, col.get("quantity")))
        if date is None:
            result.bad_rows.append(BadRow(line, "ongeldige datum", text))
            continue
        if not ISIN_RE.match(isin):
            result.bad_rows.append(BadRow(line, "ongeldige ISIN", text))
            continue
        if quantity is None:
            result.bad_rows.append(BadRow(line, "ongeldig aantal", text))
            continue
        price, price_currency = _amount_and_currency(row, col.get("price"))
        value_eur, _ = _amount_and_currency(row, col.get("value"))
        fees, _ = _amount_and_currency(row, col.get("fees"))
        total_eur, _ = _amount_and_currency(row, col.get("total"))
        result.transactions.append(
            ParsedTransaction(
                row_hash=_make_hash("tx", row, seen),
                date=date,
                time=_cell(row, col.get("time")),
                isin=isin,
                product=_cell(row, col.get("product")),
                exchange=_cell(row, col.get("exchange")) or None,
                quantity=quantity,
                price=price,
                price_currency=price_currency,
                value_eur=value_eur,
                fees_eur=abs(fees or 0.0),
                total_eur=total_eur,
                order_id=_cell(row, col.get("order_id")) or None,
            )
        )
    return result


def _parse_account(headers: list[str], rows: list[list[str]]) -> ParseResult:
    col = _find_columns(headers, ACCOUNT_COLUMNS)
    result = ParseResult(kind="account")
    seen: Counter = Counter()
    for line, row in enumerate(rows, start=2):
        date = parse_date(_cell(row, col.get("date")))
        if date is None:
            result.bad_rows.append(BadRow(line, "ongeldige datum", ",".join(row)[:200]))
            continue
        description = _cell(row, col.get("description"))
        amount, currency = _amount_and_currency(row, col.get("amount"))
        isin = _cell(row, col.get("isin")).upper()
        entry = ParsedAccountEntry(
            row_hash=_make_hash("acc", row, seen),
            date=date,
            value_date=parse_date(_cell(row, col.get("value_date"))),
            isin=isin if ISIN_RE.match(isin) else None,
            product=_cell(row, col.get("product")),
            description=description,
            kind=classify(description),
            currency=currency,
            amount=amount,
            fx=parse_number(_cell(row, col.get("fx"))),
        )
        result.entries.append(entry)
        if entry.kind == "other":
            result.unrecognised.append(entry)
    return result
