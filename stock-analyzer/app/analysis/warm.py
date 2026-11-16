"""Calculate page results in the background after the data changes.

Called after a refresh, an import, a settings change and at startup, so the next visitor
finds the results ready instead of waiting for them. One run at a time: a request made
while a run is busy starts one more run when it finishes, which then sees the newest data.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import session_scope
from app.models import Portfolio

log = logging.getLogger(__name__)

_lock = threading.Lock()
_state = {"running": False, "again": False}


def warm_up(factory: sessionmaker[Session]) -> None:
    with _lock:
        if _state["running"]:
            _state["again"] = True
            return
        _state["running"] = True
    threading.Thread(target=_loop, args=(factory,), daemon=True, name="warm-up").start()


def is_running() -> bool:
    with _lock:
        return _state["running"]


def _loop(factory) -> None:
    while True:
        try:
            _warm(factory)
        except Exception:
            log.exception("Background calculation failed")
        with _lock:
            if not _state["again"]:
                _state["running"] = False
                return
            _state["again"] = False


def _warm(factory) -> None:
    from app.analysis.comparison import build_comparison
    from app.analysis.screener import screen_for
    from app.analysis.service import compute_signals
    from app.web.routes import chart_for

    with session_scope(factory) as session:
        owners = session.execute(select(Portfolio.id, Portfolio.user_id)).all()
    for portfolio_id, user_id in owners:
        with session_scope(factory) as session:
            portfolio, _, _ = compute_signals(session, portfolio_id, user_id)
            build_comparison(session, portfolio_id)
            for ticker in {p.ticker for p in portfolio.positions if p.ticker}:
                chart_for(session, ticker, wait=None)
            screen_for(session, portfolio_id, user_id, "balanced", wait=None)
