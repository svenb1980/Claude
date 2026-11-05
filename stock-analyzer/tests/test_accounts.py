"""Accounts, separation between users, and migrating the single-user database."""
from __future__ import annotations

import sqlite3

import pytest

from app import auth
from app.db import make_engine, make_session_factory
from app.importers.degiro_csv import parse_export
from app.importers.store import save_export
from app.migrations import has_legacy_data, migrate
from app.models import AccountEntry, Portfolio, Setting, Transaction, User
from app.portfolio.positions import build_portfolio
from tests.conftest import ISIN_NL, make_account_csv, make_transactions_csv

PASSWORD = "testwachtwoord-1"


def test_password_hash_roundtrip():
    stored = auth.hash_password(PASSWORD)
    assert PASSWORD not in stored
    assert auth.verify_password(PASSWORD, stored)
    assert not auth.verify_password("iets anders", stored)
    assert not auth.verify_password(PASSWORD, "kapot")


def test_create_user_gets_a_portfolio(session):
    user = auth.create_user(session, "alice", PASSWORD)
    assert session.query(Portfolio).filter_by(user_id=user.id).count() == 1
    assert not user.is_admin


@pytest.mark.parametrize("name,password,error", [
    ("x", PASSWORD, "acc_bad_username"),
    ("met spatie", PASSWORD, "acc_bad_username"),
    ("alice", "kort", "acc_short_password"),
])
def test_invalid_accounts_are_refused(session, name, password, error):
    with pytest.raises(auth.AccountError, match=error):
        auth.create_user(session, name, password)


def test_usernames_are_unique_ignoring_case(session):
    auth.create_user(session, "alice", PASSWORD)
    with pytest.raises(auth.AccountError, match="acc_username_taken"):
        auth.create_user(session, "ALICE", PASSWORD)


def test_authenticate(session):
    auth.create_user(session, "alice", PASSWORD)
    assert auth.authenticate(session, "Alice", PASSWORD) is not None
    assert auth.authenticate(session, "alice", "fout-wachtwoord") is None
    assert auth.authenticate(session, "niemand", PASSWORD) is None


def test_lockout_after_repeated_failures():
    name = "lockout-test"
    auth.clear_failures(name)
    for _ in range(auth.MAX_FAILURES):
        assert not auth.is_locked_out(name)
        auth.record_failure(name)
    assert auth.is_locked_out(name)
    auth.clear_failures(name)


def test_same_export_in_two_portfolios_stays_separate(session):
    assert save_export(session, parse_export(make_transactions_csv()), 1) == 4
    assert save_export(session, parse_export(make_transactions_csv()), 2) == 4
    assert session.query(Transaction).count() == 8
    assert build_portfolio(session, 1).positions[0].quantity == build_portfolio(session, 2).positions[0].quantity
    assert build_portfolio(session, 3).positions == []


def test_delete_user_removes_their_data_only(session):
    alice = auth.create_user(session, "alice", PASSWORD)
    bob = auth.create_user(session, "bob", PASSWORD)
    a_id = session.query(Portfolio).filter_by(user_id=alice.id).one().id
    b_id = session.query(Portfolio).filter_by(user_id=bob.id).one().id
    save_export(session, parse_export(make_transactions_csv()), a_id)
    save_export(session, parse_export(make_account_csv()), a_id)
    save_export(session, parse_export(make_transactions_csv()), b_id)

    auth.delete_user(session, alice)
    assert session.get(User, alice.id) is None
    assert session.query(Transaction).filter_by(portfolio_id=a_id).count() == 0
    assert session.query(AccountEntry).filter_by(portfolio_id=a_id).count() == 0
    assert session.query(Transaction).filter_by(portfolio_id=b_id).count() == 4


OLD_SCHEMA = """
CREATE TABLE transactions (row_hash VARCHAR(40) PRIMARY KEY, date DATE, time VARCHAR(8), isin VARCHAR(12), product VARCHAR(200),
  exchange VARCHAR(16), quantity FLOAT, price FLOAT, price_currency VARCHAR(8), value_eur FLOAT, fees_eur FLOAT, total_eur FLOAT, order_id VARCHAR(64));
CREATE INDEX ix_transactions_date ON transactions (date);
CREATE INDEX ix_transactions_isin ON transactions (isin);
CREATE TABLE account_entries (row_hash VARCHAR(40) PRIMARY KEY, date DATE, value_date DATE, isin VARCHAR(12), product VARCHAR(200),
  description VARCHAR(300), kind VARCHAR(16), currency VARCHAR(8), amount FLOAT, fx FLOAT);
CREATE INDEX ix_account_entries_date ON account_entries (date);
CREATE INDEX ix_account_entries_isin ON account_entries (isin);
CREATE TABLE prices (ticker VARCHAR(32), date DATE, close FLOAT, adj_close FLOAT, volume FLOAT, PRIMARY KEY (ticker, date));
CREATE TABLE settings (key VARCHAR(64) PRIMARY KEY, value_json TEXT);
INSERT INTO transactions VALUES ('h1', '2024-01-10', '10:00', 'NL0000000001', 'ACME', 'EAM', 10, 100, 'EUR', -1000, 2, -1002, 'o1');
INSERT INTO account_entries VALUES ('h2', '2025-05-05', '2025-05-05', 'NL0000000001', 'ACME', 'Dividend', 'dividend', 'EUR', 25, NULL);
INSERT INTO prices VALUES ('ACME.AS', '2026-11-03', 120, 120, 1000);
INSERT INTO settings VALUES ('analysis', '{"sell_below": 30.0}');
"""


def test_migration_keeps_old_imports_and_gives_them_to_first_admin(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_SCHEMA)
    engine = make_engine(path)
    migrate(engine)
    factory = make_session_factory(engine)
    session = factory()
    assert has_legacy_data(session)
    assert session.query(Transaction).count() == 0

    user = auth.create_user(session, "sven-test", PASSWORD, is_admin=True)
    session.commit()
    portfolio = session.query(Portfolio).filter_by(user_id=user.id).one()
    assert session.query(Transaction).filter_by(portfolio_id=portfolio.id).count() == 1
    assert session.query(AccountEntry).filter_by(portfolio_id=portfolio.id).count() == 1
    assert session.get(Setting, f"analysis:{user.id}") is not None
    assert not has_legacy_data(session)
    assert build_portfolio(session, portfolio.id).positions[0].isin == ISIN_NL

    # A second user must not receive anything.
    other = auth.create_user(session, "tweede", PASSWORD, is_admin=True)
    other_portfolio = session.query(Portfolio).filter_by(user_id=other.id).one()
    assert session.query(Transaction).filter_by(portfolio_id=other_portfolio.id).count() == 0
    session.close()
    engine.dispose()


def test_migration_runs_twice_without_harm(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_SCHEMA)
    engine = make_engine(path)
    migrate(engine)
    migrate(engine)
    session = make_session_factory(engine)()
    assert has_legacy_data(session)
    session.close()
    engine.dispose()


def test_prices_get_high_and_low_columns(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_SCHEMA)
    engine = make_engine(path)
    migrate(engine)
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(prices)")}
        assert {"high", "low"} <= columns
        assert conn.execute("SELECT close FROM prices").fetchone()[0] == 120
    engine.dispose()
