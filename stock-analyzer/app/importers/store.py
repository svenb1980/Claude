"""Save a parsed export to the database, skipping rows that already exist."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importers.degiro_csv import ParseResult
from app.models import AccountEntry, Product, Transaction
from app.settings_store import bump_data_version


@dataclass
class DuplicateCheck:
    new: int
    duplicates: int


def _existing(session: Session, model, portfolio_id: int, hashes: list[str]) -> set[str]:
    found: set[str] = set()
    # SQLite limits the number of bound variables per statement.
    for start in range(0, len(hashes), 500):
        chunk = hashes[start : start + 500]
        found.update(session.scalars(
            select(model.row_hash).where(model.portfolio_id == portfolio_id, model.row_hash.in_(chunk))
        ))
    return found


def check_duplicates(session: Session, parsed: ParseResult, portfolio_id: int) -> DuplicateCheck:
    model = Transaction if parsed.kind == "transactions" else AccountEntry
    rows = parsed.transactions if parsed.kind == "transactions" else parsed.entries
    existing = _existing(session, model, portfolio_id, [r.row_hash for r in rows])
    return DuplicateCheck(new=len(rows) - len(existing), duplicates=len(existing))


def _ensure_product(session: Session, isin: str, name: str, exchange: str | None) -> None:
    product = session.get(Product, isin)
    if product is None:
        session.add(Product(isin=isin, name=name, exchange=exchange))
        session.flush()
    else:
        product.name = name or product.name
        product.exchange = exchange or product.exchange


def save_export(session: Session, parsed: ParseResult, portfolio_id: int) -> int:
    """Store new rows and return how many were added."""
    added = 0
    if parsed.kind == "transactions":
        existing = _existing(session, Transaction, portfolio_id, [r.row_hash for r in parsed.transactions])
        for row in sorted(parsed.transactions, key=lambda r: (r.date, r.time)):
            _ensure_product(session, row.isin, row.product, row.exchange)
            if row.row_hash not in existing:
                session.add(Transaction(portfolio_id=portfolio_id, **asdict(row)))
                added += 1
    else:
        existing = _existing(session, AccountEntry, portfolio_id, [r.row_hash for r in parsed.entries])
        for row in parsed.entries:
            if row.isin:
                _ensure_product(session, row.isin, row.product, None)
            if row.row_hash not in existing:
                session.add(AccountEntry(portfolio_id=portfolio_id, **asdict(row)))
                added += 1
    if added:
        bump_data_version(session)
    session.flush()
    return added
