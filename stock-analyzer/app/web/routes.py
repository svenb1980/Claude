"""Pages and form handlers.

Portfolio data is always read through `_current_portfolio`, which only returns
portfolios owned by the logged-in user.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
import threading
import time
from collections import Counter
from pathlib import Path
from secrets import token_hex
from urllib.parse import urlsplit

import pandas as pd
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined
from sqlalchemy import func, select

from app import auth
from app.analysis.backtest import run_backtest
from app.analysis.comparison import MARKETS, PERIODS, build_comparison, chart_payload
from app.analysis.levels import break_even_move_pct, daily_levels, intraday_levels, split_sessions
from app.analysis.scoring import FACTORS
from app.analysis.screener import PRESETS, SCREEN_FACTORS, portfolio_profile, run_screen, score_stock, _label
from app.analysis.service import compute_signals, load_prices
from app.ask import service as ask
from app.db import session_scope
from app.dividends.calendar import expected_dividends, month_view, received_dividends, year_totals
from app.i18n.nl import T
from app.importers.degiro_csv import UnknownFormat, parse_export
from app.importers.store import check_duplicates, save_export
from app.market.refresh import refresh_all, refresh_status
from app.market.screener_refresh import add_manual_tickers, refresh_batch, screener_counts, screener_status
from app.market.symbols import set_manual_ticker
from app.migrations import has_legacy_data
from app.models import Portfolio, Price, Product, ScreenerStock, Transaction, User
from app.portfolio.positions import average_fee_eur, import_status
from app.settings_store import bump_data_version, get_analysis_settings, get_setting, set_analysis_settings, set_setting
from app.web.formatting import FILTERS, number
from app.web.levels_view import chart_lines, daily_rows, intraday_notes, intraday_rows

log = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.undefined = StrictUndefined
templates.env.filters.update(FILTERS)
templates.env.globals["t"] = T

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
TICKER_RE = re.compile(r"^[A-Za-z0-9.\-=^]{0,32}$")
SCREEN_PAGE_SIZE = 100
INTRADAY_CACHE_SECONDS = 300
INTRADAY_SESSIONS_SHOWN = 2
DEFAULT_TRADE_VALUE_EUR = 1000.0
_backtest_lock = threading.Lock()
_backtest_running: dict = {"portfolio_id": None}
_intraday_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_intraday_lock = threading.Lock()


def _user(request: Request) -> User:
    return request.state.user


def _factory(request: Request):
    return request.app.state.session_factory


def _portfolios(session, user_id: int) -> list[Portfolio]:
    return list(session.scalars(select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)).all())


def _current_portfolio(request: Request, session) -> Portfolio:
    """The selected portfolio, if it belongs to this user. Otherwise their first one."""
    user = _user(request)
    portfolios = _portfolios(session, user.id)
    if not portfolios:
        portfolio = Portfolio(user_id=user.id, name="Mijn portefeuille")
        session.add(portfolio)
        session.flush()
        portfolios = [portfolio]
    selected = request.session.get("portfolio_id")
    for portfolio in portfolios:
        if portfolio.id == selected:
            return portfolio
    request.session["portfolio_id"] = portfolios[0].id
    return portfolios[0]


def _render(request: Request, name: str, **context) -> HTMLResponse:
    user = getattr(request.state, "user", None)
    nav_portfolios, current_id = [], None
    if user is not None:
        with session_scope(_factory(request)) as session:
            current_id = _current_portfolio(request, session).id
            nav_portfolios = _portfolios(session, user.id)
    return templates.TemplateResponse(
        request, name,
        {"user": user, "nav_portfolios": nav_portfolios, "current_portfolio_id": current_id,
         "path": request.url.path, **context},
    )


def _safe_back(request: Request, default: str = "/") -> str:
    """Return to the page the form was on, but only on this site."""
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.netloc == request.headers.get("host"):
            return parts.path + (f"?{parts.query}" if parts.query else "")
    return default


def _start_refresh(request: Request) -> None:
    factory = _factory(request)
    get_provider = request.app.state.get_provider

    def job():
        try:
            refresh_all(factory, get_provider())
        except Exception:
            log.exception("Market data refresh failed")

    threading.Thread(target=job, daemon=True, name="refresh").start()


@router.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok"})


# --- First run, login, account ----------------------------------------------

@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    with session_scope(_factory(request)) as session:
        if auth.user_count(session):
            return RedirectResponse("/login", status_code=303)
        legacy = has_legacy_data(session)
    return _render(request, "setup.html", error=None, legacy=legacy)


@router.post("/setup", response_class=HTMLResponse)
def setup_submit(request: Request, username: str = Form(""), password: str = Form("")):
    with session_scope(_factory(request)) as session:
        if auth.user_count(session):
            return RedirectResponse("/login", status_code=303)
        legacy = has_legacy_data(session)
        try:
            user = auth.create_user(session, username, password, is_admin=True)
        except auth.AccountError as exc:
            session.rollback()
            return _render(request, "setup.html", error=T[str(exc)], legacy=legacy)
        request.session.update(user_id=user.id, sv=user.session_version)
    return RedirectResponse("/", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _render(request, "login.html", error=None)


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(""), password: str = Form("")):
    if auth.is_locked_out(username):
        return _render(request, "login.html", error=T["login_locked"])
    with session_scope(_factory(request)) as session:
        user = auth.authenticate(session, username, password)
        if user is None:
            auth.record_failure(username)
            return _render(request, "login.html", error=T["login_failed"])
        auth.clear_failures(username)
        request.session.clear()
        request.session.update(user_id=user.id, sv=user.session_version)
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/account", response_class=HTMLResponse)
def account_page(request: Request):
    with session_scope(_factory(request)) as session:
        portfolios = _portfolios(session, _user(request).id)
        counts = {
            p.id: session.scalar(select(func.count()).select_from(Transaction).where(Transaction.portfolio_id == p.id))
            for p in portfolios
        }
        users = session.scalars(select(User).order_by(User.username)).all() if _user(request).is_admin else []
    return _render(
        request, "account.html", portfolios=portfolios, counts=counts, users=users,
        message=request.query_params.get("message"), error=request.query_params.get("error"),
    )


def _account_redirect(message: str | None = None, error: str | None = None) -> RedirectResponse:
    # Only i18n keys travel in the URL; the template looks up the text.
    query = f"?message={message}" if message else (f"?error={error}" if error else "")
    return RedirectResponse(f"/account{query}", status_code=303)


@router.post("/account/password")
def account_password(request: Request, current: str = Form(""), new: str = Form("")):
    with session_scope(_factory(request)) as session:
        user = session.get(User, _user(request).id)
        if not auth.verify_password(current, user.password_hash):
            return _account_redirect(error="acc_wrong_password")
        try:
            auth.set_password(session, user, new)
        except auth.AccountError as exc:
            return _account_redirect(error=str(exc))
        request.session["sv"] = user.session_version
    return _account_redirect(message="acc_saved")


@router.post("/portfolios/select")
def portfolio_select(request: Request, portfolio_id: int = Form(...)):
    with session_scope(_factory(request)) as session:
        portfolio = session.get(Portfolio, portfolio_id)
        if portfolio is not None and portfolio.user_id == _user(request).id:
            request.session["portfolio_id"] = portfolio.id
    return RedirectResponse(_safe_back(request), status_code=303)


@router.post("/portfolios")
def portfolio_create(request: Request, name: str = Form("")):
    cleaned = name.strip()[:80]
    if not cleaned:
        return _account_redirect(error="acc_bad_portfolio_name")
    with session_scope(_factory(request)) as session:
        portfolio = Portfolio(user_id=_user(request).id, name=cleaned)
        session.add(portfolio)
        session.flush()
        request.session["portfolio_id"] = portfolio.id
    return _account_redirect(message="acc_saved")


def _own_portfolio(request: Request, session, portfolio_id: int) -> Portfolio | None:
    portfolio = session.get(Portfolio, portfolio_id)
    return portfolio if portfolio is not None and portfolio.user_id == _user(request).id else None


@router.post("/portfolios/{portfolio_id}/rename")
def portfolio_rename(request: Request, portfolio_id: int, name: str = Form("")):
    cleaned = name.strip()[:80]
    if not cleaned:
        return _account_redirect(error="acc_bad_portfolio_name")
    with session_scope(_factory(request)) as session:
        portfolio = _own_portfolio(request, session, portfolio_id)
        if portfolio is not None:
            portfolio.name = cleaned
    return _account_redirect(message="acc_saved")


@router.post("/portfolios/{portfolio_id}/delete")
def portfolio_delete(request: Request, portfolio_id: int, confirm_name: str = Form("")):
    with session_scope(_factory(request)) as session:
        portfolio = _own_portfolio(request, session, portfolio_id)
        if portfolio is None:
            return _account_redirect()
        if len(_portfolios(session, _user(request).id)) <= 1:
            return _account_redirect(error="acc_last_portfolio")
        if confirm_name.strip() != portfolio.name:
            return _account_redirect(error="acc_confirm_mismatch")
        auth.delete_portfolio(session, portfolio)
    request.session.pop("portfolio_id", None)
    return _account_redirect(message="acc_saved")


def _require_admin(request: Request) -> bool:
    return _user(request).is_admin


@router.post("/users")
def user_create(request: Request, username: str = Form(""), password: str = Form(""), is_admin: str = Form("")):
    if not _require_admin(request):
        return RedirectResponse("/", status_code=303)
    with session_scope(_factory(request)) as session:
        try:
            auth.create_user(session, username, password, is_admin=False)
            if is_admin:
                created = session.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
                created.is_admin = True
        except auth.AccountError as exc:
            session.rollback()
            return _account_redirect(error=str(exc))
    return _account_redirect(message="acc_saved")


@router.post("/users/{user_id}/password")
def user_reset_password(request: Request, user_id: int, password: str = Form("")):
    if not _require_admin(request):
        return RedirectResponse("/", status_code=303)
    with session_scope(_factory(request)) as session:
        target = session.get(User, user_id)
        if target is not None:
            try:
                auth.set_password(session, target, password)
            except auth.AccountError as exc:
                return _account_redirect(error=str(exc))
    return _account_redirect(message="acc_saved")


@router.post("/users/{user_id}/delete")
def user_delete(request: Request, user_id: int, confirm_name: str = Form("")):
    if not _require_admin(request):
        return RedirectResponse("/", status_code=303)
    with session_scope(_factory(request)) as session:
        target = session.get(User, user_id)
        if target is None:
            return _account_redirect()
        if target.id == _user(request).id:
            return _account_redirect(error="acc_cannot_delete_self")
        if confirm_name.strip() != target.username:
            return _account_redirect(error="acc_confirm_mismatch")
        auth.delete_user(session, target)
    return _account_redirect(message="acc_saved")


# --- Dashboard -------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        portfolio, signals, analysis = compute_signals(session, current.id, _user(request).id)
        status = refresh_status(session)
        upcoming = expected_dividends(session, current.id)[:6]
        comparison = build_comparison(session, current.id)
    sectors: dict[str, float] = {}
    for position in portfolio.positions:
        if position.weight_pct is not None:
            key = position.sector or T["unknown_sector"]
            sectors[key] = sectors.get(key, 0.0) + position.weight_pct
    allocation = sorted(sectors.items(), key=lambda item: -item[1])
    signal_by_isin = {s.position.isin: s for s in signals}
    return _render(
        request, "dashboard.html",
        portfolio=portfolio, signals=signal_by_isin, status=status,
        upcoming=upcoming, allocation=allocation, comparison=comparison,
        periods=[name for name, _ in PERIODS], market_keys=[key for key, _, _ in MARKETS if key in comparison.markets],
    )


@router.get("/api/market-comparison")
def market_comparison_api(request: Request):
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        comparison = build_comparison(session, current.id)
    if not comparison.available:
        return JSONResponse({"error": T["cmp_no_data"]})
    return JSONResponse(_finite(chart_payload(comparison, T)))


@router.post("/refresh")
def refresh(request: Request):
    _start_refresh(request)
    return RedirectResponse(_safe_back(request), status_code=303)


# --- Signals ---------------------------------------------------------------

LABEL_ORDER = {"sell": 0, "buy": 1, "hold": 2, "insufficient": 3}


@router.get("/signals", response_class=HTMLResponse)
def signals_page(request: Request):
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        portfolio, signals, analysis = compute_signals(session, current.id, _user(request).id)
    ordered = sorted(signals, key=lambda s: (LABEL_ORDER[s.result.label], -(s.result.total or 0)))
    return _render(request, "signals.html", signals=ordered, analysis=analysis, portfolio=portfolio)


def _price_chart(prices: pd.DataFrame, rows: list[dict]) -> dict:
    """Five years of daily closes with the 200-day average and the sell lines."""
    sma = prices["close"].rolling(200).mean()
    recent = prices.iloc[-1260:]
    points = []
    for date, close in recent["close"].items():
        value = sma.get(date)
        points.append({"d": date.date().isoformat(), "p": round(float(close), 4),
                       "s": None if pd.isna(value) else round(float(value), 4)})
    return {
        "points": points,
        "series": [{"key": "p", "label": T["stock_chart_price"], "slot": 1},
                   {"key": "s", "label": T["stock_chart_sma"], "slot": 4}],
        "levels": chart_lines(rows),
        "ranges": [{"label": label, "days": days} for label, days in
                   (("1M", 21), ("3M", 63), ("6M", 126), ("1J", 252), ("2J", 504), ("5J", 1260))],
        "defaultRange": 126,
    }


def _chart_context(session, ticker: str | None) -> dict:
    """Everything the shared price chart with sell lines needs."""
    if not ticker:
        return {"chart": None, "level_rows": [], "level_info": None, "table": [], "chart_ticker": None}
    prices = load_prices(session, ticker)
    if prices.empty:
        return {"chart": None, "level_rows": [], "level_info": None, "table": [], "chart_ticker": ticker}
    levels = daily_levels(prices)
    rows = daily_rows(levels) if levels else []
    monthly = prices["close"].iloc[-252:].resample("ME").last().dropna()
    return {
        "chart": _price_chart(prices, rows),
        "level_rows": rows,
        "level_info": {"atr_pct": levels.get("atr_pct"), "as_of": levels.get("as_of"), "price": levels.get("price")} if levels else None,
        "table": [{"date": d.date(), "close": float(v)} for d, v in monthly.items()],
        "chart_ticker": ticker,
    }


@router.get("/stocks/{isin}", response_class=HTMLResponse)
def stock_page(request: Request, isin: str):
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        portfolio, signals, analysis = compute_signals(session, current.id, _user(request).id)
        signal = next((s for s in signals if s.position.isin == isin), None)
        if signal is None:
            return _render(request, "error.html", message=T["signals_empty"])
        chart = _chart_context(session, signal.position.ticker)
        received = [r for r in received_dividends(session, current.id) if r.isin == isin]
    return _render(
        request, "stock.html",
        signal=signal, position=signal.position, result=signal.result, metrics=signal.metrics,
        analysis=analysis, received=received, **chart,
    )


# --- Vraag Claude -----------------------------------------------------------

def _ask_client(request: Request):
    """The Claude client, or None while no API key is set."""
    state = request.app.state
    if state.ask_client is None and ask.has_credentials():
        state.ask_client = ask.make_client()
    return state.ask_client


@router.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request, scope: str = ask.SCOPE_NONE):
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        options = ask.scope_options(session, current.id, _user(request).id)
        portfolio_id = current.id
    if scope not in {ask.SCOPE_NONE, ask.SCOPE_PORTFOLIO, *(isin for isin, _ in options)}:
        scope = ask.SCOPE_NONE
    config = request.app.state.config
    return _render(
        request, "ask.html",
        ready=_ask_client(request) is not None, options=options, scope=scope, portfolio_id=portfolio_id,
        scope_none=ask.SCOPE_NONE, scope_portfolio=ask.SCOPE_PORTFOLIO,
        max_chars=ask.MAX_QUESTION_CHARS, max_messages=ask.MAX_MESSAGES, daily_limit=config.ask_daily_limit,
    )


@router.get("/api/ask/context")
def ask_context(request: Request, scope: str = ask.SCOPE_NONE):
    """Shows the user exactly what would go along with a question."""
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        return {"context": ask.build_context(session, current.id, _user(request).id, scope)}


def _prepare_question(request: Request, scope: str) -> tuple[bool, str | None]:
    config = request.app.state.config
    with session_scope(_factory(request)) as session:
        user_id = _user(request).id
        if not ask.use_daily_allowance(session, user_id, config.ask_daily_limit):
            return False, None
        current = _current_portfolio(request, session)
        return True, ask.build_context(session, current.id, user_id, scope)


@router.post("/api/ask")
async def ask_question(request: Request):
    client = _ask_client(request)
    if client is None:
        return JSONResponse({"error": T["ask_not_ready_title"]}, status_code=503)
    body = await request.body()
    if len(body) > ask.MAX_BODY_BYTES:
        return JSONResponse({"error": T["ask_error_conversation"]}, status_code=413)
    try:
        payload = json.loads(body)
        messages = ask.validate_messages(payload.get("messages"))
    except (ValueError, AttributeError):
        return JSONResponse({"error": T["ask_error_conversation"]}, status_code=400)
    scope = str(payload.get("scope", ask.SCOPE_NONE))
    allowed, context = await run_in_threadpool(_prepare_question, request, scope)
    if not allowed:
        limit = request.app.state.config.ask_daily_limit
        return JSONResponse({"error": T["ask_limit"].format(limit=limit)}, status_code=429)
    system = ask.build_system(ask.load_skill(), context)
    model = request.app.state.config.ask_model

    def lines():
        for event in ask.stream_answer(client, model, system, messages):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


# --- Screener --------------------------------------------------------------

def _profile(session, portfolio_id: int, user_id: int) -> dict:
    portfolio, _, _ = compute_signals(session, portfolio_id, user_id)
    held = {p.isin for p in portfolio.positions}
    products = session.scalars(select(Product).where(Product.isin.in_(held))).all() if held else []
    names = {p.fundamentals.get("name") for p in products if p.fundamentals.get("name")}
    return portfolio_profile(portfolio.positions, names)


@router.get("/screener", response_class=HTMLResponse)
def screener_page(request: Request, preset: str = "balanced", sector: str = "", region: str = "",
                  min_yield: str = "", label: str = "", q: str = ""):
    preset = preset if preset in PRESETS else "balanced"
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        profile = _profile(session, current.id, _user(request).id)
        results = run_screen(session, profile, preset)
        counts = screener_counts(session)
        status = screener_status(session)
    sectors = sorted({r.sector for r in results if r.sector})
    regions = sorted({r.country for r in results if r.country})
    filtered = results
    if sector:
        filtered = [r for r in filtered if r.sector == sector]
    if region:
        filtered = [r for r in filtered if r.country == region]
    if label:
        filtered = [r for r in filtered if r.label == label]
    try:
        minimum = float(min_yield.replace(",", ".")) / 100 if min_yield else None
    except ValueError:
        minimum = None
    if minimum is not None:
        filtered = [r for r in filtered if (r.dividend_yield or 0) >= minimum]
    if q:
        needle = q.strip().lower()
        filtered = [r for r in filtered if needle in r.name.lower() or needle in r.ticker.lower()]
    return _render(
        request, "screener.html",
        results=filtered[:SCREEN_PAGE_SIZE], total=len(filtered), counts=counts, status=status,
        presets=list(PRESETS), preset=preset, weights=PRESETS[preset], factors=SCREEN_FACTORS,
        sectors=sectors, regions=regions,
        selected={"sector": sector, "region": region, "min_yield": min_yield, "label": label, "q": q},
        profile=profile,
    )


@router.post("/screener/refresh")
def screener_refresh(request: Request):
    if _user(request).is_admin:
        factory, get_provider = _factory(request), request.app.state.get_provider
        batch = request.app.state.config.screener_batch

        def job():
            try:
                refresh_batch(factory, get_provider(), batch)
            except Exception:
                log.exception("Screener refresh failed")

        threading.Thread(target=job, daemon=True, name="screener").start()
    return RedirectResponse("/screener", status_code=303)


@router.get("/market/{ticker}", response_class=HTMLResponse)
def market_page(request: Request, ticker: str, preset: str = "balanced"):
    preset = preset if preset in PRESETS else "balanced"
    with session_scope(_factory(request)) as session:
        stock = session.get(ScreenerStock, ticker)
        if stock is None:
            return _render(request, "error.html", message=T["scr_unknown"])
        current = _current_portfolio(request, session)
        profile = _profile(session, current.id, _user(request).id)
        data = json.loads(stock.data_json or "{}")
        score, confidence, factors = score_stock(data, profile, PRESETS[preset]) if data else (None, 0.0, [])
        chart = _chart_context(session, ticker)
    return _render(
        request, "market.html", stock=stock, score=score, confidence=confidence, factors=factors,
        label=_label(score, confidence), metrics=data.get("metrics", {}), fundamentals=data.get("fundamentals", {}),
        preset=preset, weights=PRESETS[preset], **chart,
    )


# --- Intraday --------------------------------------------------------------

def _known_ticker(session, ticker: str) -> bool:
    if session.get(ScreenerStock, ticker) is not None:
        return True
    return session.scalar(select(Product.isin).where(Product.ticker == ticker).limit(1)) is not None


def _intraday_bars(request: Request, ticker: str) -> pd.DataFrame:
    now = time.time()
    with _intraday_lock:
        cached = _intraday_cache.get(ticker)
        if cached and now - cached[0] < INTRADAY_CACHE_SECONDS:
            return cached[1]
    bars = request.app.state.get_provider().intraday(ticker)
    with _intraday_lock:
        if len(_intraday_cache) > 50:
            _intraday_cache.clear()
        _intraday_cache[ticker] = (now, bars)
    return bars


@router.get("/api/intraday/{ticker}")
def intraday_api(request: Request, ticker: str):
    if not TICKER_RE.match(ticker):
        return JSONResponse({"error": T["intra_unknown"]}, status_code=404)
    with session_scope(_factory(request)) as session:
        if not _known_ticker(session, ticker):
            return JSONResponse({"error": T["intra_unknown"]}, status_code=404)
        current = _current_portfolio(request, session)
        fee = average_fee_eur(session, current.id)
    try:
        bars = _intraday_bars(request, ticker)
    except Exception as exc:
        log.warning("Intraday data failed for %s: %s", ticker, exc)
        return JSONResponse({"error": T["intra_failed"]}, status_code=502)
    result = intraday_levels(bars) if not bars.empty else {}
    if not result:
        return JSONResponse({"error": T["intra_no_data"]}, status_code=200)
    rows = intraday_rows(result)
    shown = pd.concat(split_sessions(bars)[-INTRADAY_SESSIONS_SHOWN:])
    points = [{"t": ts.isoformat(), "p": round(float(close), 4)} for ts, close in shown["close"].items()]
    last_bar = result["last_bar"]
    age_minutes = (pd.Timestamp.now(tz=last_bar.tz) - last_bar).total_seconds() / 60
    break_even = break_even_move_pct(fee, DEFAULT_TRADE_VALUE_EUR)
    return JSONResponse(_finite({
        "chart": {
            "points": points, "dateKey": "t", "intraday": True,
            "series": [{"key": "p", "label": T["stock_chart_price"], "slot": 1}],
            "levels": chart_lines(rows),
        },
        "rows": [{**row, "priceText": number(row["price"])} for row in rows],
        "notes": intraday_notes(
            last_bar.strftime("%d-%m-%Y %H:%M"), round(age_minutes), fee, DEFAULT_TRADE_VALUE_EUR,
            break_even, result["sessions_tested"],
        ),
    }))


def _finite(value):
    """JSON has no NaN or Infinity."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


# --- Dividends -------------------------------------------------------------

@router.get("/dividends", response_class=HTMLResponse)
def dividends_page(request: Request, year: int | None = None, month: int | None = None):
    today = dt.date.today()
    year = year if year and 1990 <= year <= 2100 else today.year
    month = month if month and 1 <= month <= 12 else today.month
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        received = received_dividends(session, current.id)
        expected = expected_dividends(session, current.id, today=today)
    previous = (year - 1, 12) if month == 1 else (year, month - 1)
    following = (year + 1, 1) if month == 12 else (year, month + 1)
    return _render(
        request, "dividends.html",
        year=year, month=month, today=today, previous=previous, following=following,
        weeks=month_view(year, month, received, expected),
        totals=year_totals(year, received, expected),
        received=received, expected=expected,
    )


# --- Import ----------------------------------------------------------------

def _import_context(request: Request, session) -> dict:
    current = _current_portfolio(request, session)
    return {"status": import_status(session, current.id), "portfolio_name": current.name}


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    with session_scope(_factory(request)) as session:
        context = _import_context(request, session)
    return _render(request, "import.html", preview=None, error=None, done=request.query_params.get("done"), **context)


@router.post("/import", response_class=HTMLResponse)
async def import_preview(request: Request, file: UploadFile = File(...)):
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        portfolio_id = current.id
        context = _import_context(request, session)
        if len(raw) > MAX_UPLOAD_BYTES:
            return _render(request, "import.html", preview=None, error=T["imp_too_large"], done=None, **context)
        try:
            parsed = parse_export(raw)
        except UnknownFormat as exc:
            return _render(request, "import.html", preview=None, error=str(exc), done=None, **context)
        check = check_duplicates(session, parsed, portfolio_id)
    rows = parsed.transactions if parsed.kind == "transactions" else parsed.entries
    dates = [r.date for r in rows]
    token = token_hex(16)
    (request.app.state.config.upload_dir / f"{portfolio_id}-{token}.upload").write_bytes(raw)
    preview = {
        "token": token,
        "kind": parsed.kind,
        "rows": parsed.row_count,
        "new": check.new,
        "duplicates": check.duplicates,
        "first": min(dates) if dates else None,
        "last": max(dates) if dates else None,
        "bad_rows": parsed.bad_rows[:50],
        "bad_count": len(parsed.bad_rows),
        "unrecognised": sorted(Counter(e.description for e in parsed.unrecognised).items())[:50],
        "kinds": sorted(Counter(e.kind for e in parsed.entries).items()),
    }
    return _render(request, "import.html", preview=preview, error=None, done=None, **context)


def _upload_path(request: Request, portfolio_id: int, token: str) -> Path | None:
    """An upload can only be read back through the portfolio it was made for."""
    if not TOKEN_RE.match(token):
        return None
    return request.app.state.config.upload_dir / f"{portfolio_id}-{token}.upload"


@router.post("/import/confirm", response_class=HTMLResponse)
def import_confirm(request: Request, token: str = Form(...)):
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        path = _upload_path(request, current.id, token)
        if path is None or not path.exists():
            context = _import_context(request, session)
            return _render(request, "import.html", preview=None, error=T["imp_expired"], done=None, **context)
        parsed = parse_export(path.read_bytes())
        added = save_export(session, parsed, current.id)
    path.unlink(missing_ok=True)
    _start_refresh(request)
    return RedirectResponse(f"/import?done={added}", status_code=303)


@router.post("/import/cancel")
def import_cancel(request: Request, token: str = Form(...)):
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        path = _upload_path(request, current.id, token)
    if path is not None:
        path.unlink(missing_ok=True)
    return RedirectResponse("/import", status_code=303)


# --- Settings --------------------------------------------------------------

def _settings_context(request: Request, session) -> dict:
    current = _current_portfolio(request, session)
    # Only stocks in this user's portfolios: what others hold stays private.
    owned = [p.id for p in _portfolios(session, _user(request).id)]
    isins = set(session.scalars(select(Transaction.isin).where(Transaction.portfolio_id.in_(owned)).distinct()))
    products = [p for p in session.scalars(select(Product).order_by(Product.name)).all() if p.isin in isins]
    tickers = [p.ticker for p in products if p.ticker]
    last_dates = dict(session.execute(
        select(Price.ticker, func.max(Price.date)).where(Price.ticker.in_(tickers)).group_by(Price.ticker)
    ).all()) if tickers else {}
    return {
        "analysis": get_analysis_settings(session, _user(request).id),
        "factors": FACTORS,
        "products": products,
        "last_dates": last_dates,
        "status": refresh_status(session),
        "screener_counts": screener_counts(session),
        "portfolio_name": current.name,
    }


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    with session_scope(_factory(request)) as session:
        context = _settings_context(request, session)
    saved = request.query_params.get("saved") == "1"
    return _render(request, "settings.html", saved=saved, error=None, **context)


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(request: Request):
    form = await request.form()
    error = None
    values: dict = {}
    try:
        weights = {key: float(form.get(f"weight_{key}", "0").replace(",", ".")) for key in FACTORS}
        values = {
            "weights": weights,
            "sell_below": float(str(form.get("sell_below")).replace(",", ".")),
            "buy_from": float(str(form.get("buy_from")).replace(",", ".")),
            "max_position_pct": float(str(form.get("max_position_pct")).replace(",", ".")),
            "min_confidence_pct": float(str(form.get("min_confidence_pct")).replace(",", ".")),
            "risk_free_pct": float(str(form.get("risk_free_pct")).replace(",", ".")),
            "benchmark": str(form.get("benchmark", "")).strip().upper(),
        }
        if any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
            error = T["set_invalid_weights"]
        elif values["sell_below"] >= values["buy_from"]:
            error = T["set_invalid_thresholds"]
        elif values["max_position_pct"] <= 0 or not values["benchmark"] or not TICKER_RE.match(values["benchmark"]):
            error = T["set_benchmark"]
    except (TypeError, ValueError) as exc:
        error = str(exc)
    with session_scope(_factory(request)) as session:
        if error is None:
            set_analysis_settings(session, _user(request).id, values)
            bump_data_version(session)
        else:
            context = _settings_context(request, session)
    if error is None:
        return RedirectResponse("/settings?saved=1", status_code=303)
    return _render(request, "settings.html", saved=False, error=T["set_invalid"].format(error=error), **context)


@router.post("/settings/ticker")
def settings_ticker(request: Request, isin: str = Form(...), ticker: str = Form("")):
    if TICKER_RE.match(ticker.strip()):
        with session_scope(_factory(request)) as session:
            owned = [p.id for p in _portfolios(session, _user(request).id)]
            has_it = session.scalar(
                select(Transaction.isin).where(Transaction.portfolio_id.in_(owned), Transaction.isin == isin).limit(1)
            )
            if has_it and session.get(Product, isin) is not None:
                set_manual_ticker(session, isin, ticker)
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/settings/universe")
def settings_universe(request: Request, tickers: str = Form("")):
    if _user(request).is_admin:
        cleaned = [t.strip().upper() for t in re.split(r"[\s,;]+", tickers) if t.strip()]
        valid = [t for t in cleaned if TICKER_RE.match(t)]
        with session_scope(_factory(request)) as session:
            add_manual_tickers(session, valid)
    return RedirectResponse("/settings?saved=1", status_code=303)


# --- Backtest --------------------------------------------------------------

def _run_backtest_job(factory, portfolio_id: int, user_id: int) -> None:
    key = f"backtest:{portfolio_id}"
    try:
        with session_scope(factory) as session:
            portfolio, _, analysis = compute_signals(session, portfolio_id, user_id)
            held = {p.ticker for p in portfolio.positions if p.ticker}
            prices = {t: load_prices(session, t)["adj_close"] for t in held}
            prices = {t: s for t, s in prices.items() if not s.empty}
            bench_frame = load_prices(session, analysis["benchmark"])
        benchmark = bench_frame["adj_close"] if not bench_frame.empty else None
        result = run_backtest(prices, benchmark, analysis)
        if result is not None:
            result.pop("signals", None)
        with session_scope(factory) as session:
            set_setting(session, key, {"state": "done", "finished": dt.datetime.now().isoformat(), "result": result})
    except Exception as exc:
        log.exception("Backtest failed")
        with session_scope(factory) as session:
            set_setting(session, key, {"state": "failed", "error": str(exc)[:500]})
    finally:
        _backtest_running["portfolio_id"] = None
        _backtest_lock.release()


@router.get("/backtest", response_class=HTMLResponse)
def backtest_page(request: Request):
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        stored = get_setting(session, f"backtest:{current.id}", None)
        running = _backtest_running["portfolio_id"] == current.id
    return _render(request, "backtest.html", backtest=stored, running=running)


@router.post("/backtest/run")
def backtest_run(request: Request):
    with session_scope(_factory(request)) as session:
        current = _current_portfolio(request, session)
        portfolio_id = current.id
    # One at a time: on a Pi, parallel backtests would slow everything down.
    if _backtest_lock.acquire(blocking=False):
        _backtest_running["portfolio_id"] = portfolio_id
        threading.Thread(
            target=_run_backtest_job, args=(_factory(request), portfolio_id, _user(request).id),
            daemon=True, name="backtest",
        ).start()
    return RedirectResponse("/backtest", status_code=303)
