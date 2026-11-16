"""Pages stay responsive while data is loaded and calculated. All data here is made up."""
from __future__ import annotations

import datetime as dt
import sqlite3
import threading
import time

import pandas as pd
import pytest

from app.analysis.cache import ResultCache
from app.analysis.service import cached_prices, cached_signals, compute_signals, load_prices
from app.importers.degiro_csv import parse_export
from app.importers.store import save_export
from app.market.refresh import refresh_all
from app.market.screener_refresh import refresh_batch
from app.models import Price, ScreenerStock
from app.settings_store import bump_data_version, data_version, screener_version
from tests.conftest import PID, FakeProvider, make_transactions_csv


# --- The result cache --------------------------------------------------------

def test_the_same_result_is_calculated_once_for_simultaneous_requests():
    cache = ResultCache("test-once")
    calls = []

    def slow():
        calls.append(1)
        time.sleep(0.3)
        return "result"

    results = []
    threads = [threading.Thread(target=lambda: results.append(cache.get("k", 1, slow))) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert results == [("result", False)] * 5


def test_previous_result_is_shown_while_a_new_one_is_calculated():
    cache = ResultCache("test-stale")
    cache.get("k", 1, lambda: "old")
    release = threading.Event()

    def slow():
        release.wait(5)
        return "new"

    assert cache.get("k", 2, slow, wait=0.05) == ("old", True)
    release.set()
    for _ in range(100):
        value = cache.get("k", 2, slow, wait=0.05)
        if not value[1]:
            break
        time.sleep(0.02)
    assert value == ("new", False)


def test_first_result_is_always_waited_for():
    cache = ResultCache("test-first")
    assert cache.get("k", 1, lambda: (time.sleep(0.1), "value")[1], wait=0.01) == ("value", False)


def test_a_failure_without_previous_result_is_raised():
    cache = ResultCache("test-error")

    def broken():
        raise ValueError("kapot")

    with pytest.raises(ValueError):
        cache.get("k", 1, broken, wait=0.1)
    assert cache.get("k", 1, lambda: "ok") == ("ok", False)


def test_a_failure_keeps_showing_the_previous_result():
    cache = ResultCache("test-error-stale")
    cache.get("k", 1, lambda: "old")

    def broken():
        raise ValueError("kapot")

    assert cache.get("k", 2, broken, wait=1) == ("old", True)


def test_a_newer_version_waits_for_the_running_calculation_and_wins():
    cache = ResultCache("test-order")
    release = threading.Event()

    def old():
        release.wait(5)
        return "old"

    results = {}
    first = threading.Thread(target=lambda: results.setdefault(1, cache.get("k", 1, old)))
    first.start()
    time.sleep(0.05)
    second = threading.Thread(target=lambda: results.setdefault(2, cache.get("k", 2, lambda: "new")))
    second.start()
    time.sleep(0.05)
    assert 2 not in results  # Queued behind the running calculation, not started next to it.
    release.set()
    first.join(); second.join()
    assert results == {1: ("old", False), 2: ("new", False)}
    assert cache.get("k", 2, lambda: "again") == ("new", False)


def test_quick_changes_in_a_row_never_run_side_by_side():
    cache = ResultCache("test-pileup")
    running, most, calls = [0], [0], []
    lock = threading.Lock()

    def calculation(version):
        def run():
            with lock:
                running[0] += 1
                most[0] = max(most[0], running[0])
            calls.append(version)
            time.sleep(0.1)
            with lock:
                running[0] -= 1
            return version
        return run

    cache.get("k", 0, calculation(0))
    for version in range(1, 8):
        cache.get("k", version, calculation(version), wait=0.01)
        time.sleep(0.02)
    for _ in range(100):
        if cache.get("k", 7, calculation(7), wait=0.05) == (7, False):
            break
    assert most[0] == 1
    assert calls[-1] == 7 and len(calls) < 8  # Versions that were overtaken are skipped.


# --- Loading prices ----------------------------------------------------------

def test_prices_load_with_dates_and_missing_values(session):
    session.add_all([
        Price(ticker="T.AS", date=dt.date(2026, 1, 2), close=10.0, adj_close=9.5, volume=None, high=None, low=None),
        Price(ticker="T.AS", date=dt.date(2026, 1, 5), close=11.0, adj_close=10.5, volume=200.0, high=11.5, low=10.8),
    ])
    session.commit()
    frame = load_prices(session, "T.AS")
    assert list(frame.index) == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")]
    assert frame["adj_close"].tolist() == [9.5, 10.5]
    assert pd.isna(frame.loc["2026-01-02", "volume"]) and frame.loc["2026-01-05", "high"] == 11.5
    assert load_prices(session, "NONE.AS").empty


def test_cached_prices_follow_data_changes(session):
    session.add(Price(ticker="T.AS", date=dt.date(2026, 1, 2), close=10.0, adj_close=10.0))
    session.commit()
    assert len(cached_prices(session, "T.AS")) == 1
    session.add(Price(ticker="T.AS", date=dt.date(2026, 1, 5), close=11.0, adj_close=11.0))
    session.commit()
    assert len(cached_prices(session, "T.AS")) == 1  # Same version: still the kept frame.
    bump_data_version(session)
    session.commit()
    assert len(cached_prices(session, "T.AS")) == 2


# --- Refreshes ---------------------------------------------------------------

class LockCheckingProvider(FakeProvider):
    """Fails the test if the database is write-locked while 'Yahoo' is being waited for."""

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.locked_during: list[str] = []

    def _check(self, what):
        other = sqlite3.connect(self.db_path, timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
        except sqlite3.OperationalError:
            self.locked_during.append(what)
        finally:
            other.close()

    def price_history(self, ticker, start):
        self._check(f"prices {ticker}")
        return super().price_history(ticker, start)

    def dividends(self, ticker):
        self._check(f"dividends {ticker}")
        return super().dividends(ticker)

    def fx_history(self, currency, start):
        self._check(f"fx {currency}")
        return super().fx_history(currency, start)


def test_refresh_downloads_without_holding_the_write_lock(factory, session, tmp_path):
    save_export(session, parse_export(make_transactions_csv()), PID)
    session.commit()
    provider = LockCheckingProvider(tmp_path / "test.db")
    assert refresh_all(factory, provider)["failed"] == 0
    refresh_all(factory, provider)  # The second run only fetches recent days.
    assert provider.locked_during == []


def test_screener_refresh_leaves_portfolio_results_alone(factory, session, tmp_path):
    session.add(ScreenerStock(ticker="ACME.AS", name="Acme"))
    session.commit()
    before = data_version(session), screener_version(session)
    provider = LockCheckingProvider(tmp_path / "test.db")
    status = refresh_batch(factory, provider, 10)
    assert status["done"] == 1
    session.expire_all()
    assert data_version(session) == before[0]
    assert screener_version(session) == before[1] + 1
    assert provider.locked_during == []


def test_page_signals_come_from_the_same_calculation(factory, session, provider):
    save_export(session, parse_export(make_transactions_csv()), PID)
    session.commit()
    refresh_all(factory, provider)
    fresh = compute_signals(session, PID, 1)
    (value, stale) = cached_signals(session, PID, 1)
    assert value is fresh and stale is False
