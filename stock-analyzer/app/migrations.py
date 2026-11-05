"""Bring an existing database up to date without losing imported data.

The database version lives in SQLite's `user_version`:

- 0: a database from the single-user version, or a brand-new empty file
- 2: users and portfolios

Old imports are kept in `legacy_*` tables until the first account exists, and are then
moved into that account's first portfolio by `claim_legacy_data`.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import Base

log = logging.getLogger(__name__)
CURRENT_VERSION = 2

TX_COLUMNS = "row_hash, date, time, isin, product, exchange, quantity, price, price_currency, value_eur, fees_eur, total_eur, order_id"
ACCOUNT_COLUMNS = "row_hash, date, value_date, isin, product, description, kind, currency, amount, fx"


def migrate(engine: Engine) -> None:
    import app.models  # noqa: F401  (registers the tables)

    with engine.begin() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar()
        existing = set(inspect(conn).get_table_names())
        if version < 2 and "transactions" in existing:
            columns = {c["name"] for c in inspect(conn).get_columns("transactions")}
            if "portfolio_id" not in columns:
                log.info("Migrating single-user database to multi-user")
                conn.execute(text("ALTER TABLE transactions RENAME TO legacy_transactions"))
                conn.execute(text("ALTER TABLE account_entries RENAME TO legacy_account_entries"))
                # SQLite keeps index names when a table is renamed; they'd block the new tables.
                for row in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                    "AND tbl_name IN ('legacy_transactions','legacy_account_entries')"
                )).fetchall():
                    conn.execute(text(f'DROP INDEX "{row[0]}"'))
        if "prices" in existing:
            columns = {c["name"] for c in inspect(conn).get_columns("prices")}
            for column in ("high", "low"):
                if column not in columns:
                    conn.execute(text(f"ALTER TABLE prices ADD COLUMN {column} FLOAT"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA user_version = {CURRENT_VERSION}"))


def has_legacy_data(session: Session) -> bool:
    return "legacy_transactions" in inspect(session.connection()).get_table_names()


def claim_legacy_data(session: Session, portfolio_id: int, user_id: int) -> int:
    """Move pre-multi-user imports and settings into the given portfolio."""
    if not has_legacy_data(session):
        return 0
    params = {"pid": portfolio_id}
    moved = session.execute(text(
        f"INSERT OR IGNORE INTO transactions (portfolio_id, {TX_COLUMNS}) "
        f"SELECT :pid, {TX_COLUMNS} FROM legacy_transactions"), params).rowcount
    moved += session.execute(text(
        f"INSERT OR IGNORE INTO account_entries (portfolio_id, {ACCOUNT_COLUMNS}) "
        f"SELECT :pid, {ACCOUNT_COLUMNS} FROM legacy_account_entries"), params).rowcount
    session.execute(text("DROP TABLE legacy_transactions"))
    session.execute(text("DROP TABLE legacy_account_entries"))
    session.execute(text("UPDATE settings SET key = :new WHERE key = 'analysis'"), {"new": f"analysis:{user_id}"})
    session.execute(text("UPDATE settings SET key = :new WHERE key = 'backtest'"), {"new": f"backtest:{portfolio_id}"})
    log.info("Moved %s imported rows into portfolio %s", moved, portfolio_id)
    return moved
