"""Pages and form handlers."""
from __future__ import annotations

import datetime as dt
import hmac
import logging
import re
import threading
from collections import Counter
from pathlib import Path
from secrets import token_hex

import pandas as pd
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined
from sqlalchemy import func, select

from app.analysis.backtest import run_backtest
from app.analysis.scoring import FACTORS
from app.analysis.service import compute_signals, load_prices
from app.db import session_scope
from app.dividends.calendar import expected_dividends, month_view, received_dividends, year_totals
from app.i18n.nl import T
from app.importers.degiro_csv import UnknownFormat, parse_export
from app.importers.store import check_duplicates, save_export
from app.market.refresh import refresh_all, refresh_status
from app.market.symbols import set_manual_ticker
from app.models import Price, Product
from app.portfolio.positions import import_status
from app.settings_store import bump_data_version, get_analysis_settings, get_setting, set_setting
from app.web.formatting import FILTERS

log = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.undefined = StrictUndefined
templates.env.filters.update(FILTERS)
templates.env.globals["t"] = T

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
TICKER_RE = re.compile(r"^[A-Za-z0-9.\-=^]{0,32}$")
_backtest_lock = threading.Lock()


def _render(request: Request, name: str, **context) -> HTMLResponse:
    config = request.app.state.config
    return templates.TemplateResponse(
        request, name, {"login_enabled": bool(config.password), "path": request.url.path, **context}
    )


def _factory(request: Request):
    return request.app.state.session_factory


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


# --- Login -----------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _render(request, "login.html", failed=False)


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form("")):
    expected = request.app.state.config.password
    if expected and hmac.compare_digest(password.encode(), expected.encode()):
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=303)
    return _render(request, "login.html", failed=True)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --- Dashboard -------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with session_scope(_factory(request)) as session:
        portfolio, signals, analysis = compute_signals(session)
        status = refresh_status(session)
        upcoming = expected_dividends(session)[:6]
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
        upcoming=upcoming, allocation=allocation,
    )


@router.post("/refresh")
def refresh(request: Request):
    _start_refresh(request)
    return RedirectResponse(request.headers.get("referer") or "/", status_code=303)


# --- Signals ---------------------------------------------------------------

LABEL_ORDER = {"sell": 0, "buy": 1, "hold": 2, "insufficient": 3}


@router.get("/signals", response_class=HTMLResponse)
def signals_page(request: Request):
    with session_scope(_factory(request)) as session:
        portfolio, signals, analysis = compute_signals(session)
    ordered = sorted(signals, key=lambda s: (LABEL_ORDER[s.result.label], -(s.result.total or 0)))
    return _render(request, "signals.html", signals=ordered, analysis=analysis, portfolio=portfolio)


@router.get("/stocks/{isin}", response_class=HTMLResponse)
def stock_page(request: Request, isin: str):
    with session_scope(_factory(request)) as session:
        portfolio, signals, analysis = compute_signals(session)
        signal = next((s for s in signals if s.position.isin == isin), None)
        if signal is None:
            return _render(request, "error.html", message=T["signals_empty"])
        chart = []
        table = []
        if signal.position.ticker:
            prices = load_prices(session, signal.position.ticker)
            if not prices.empty:
                sma = prices["close"].rolling(200).mean()
                # Weekly points are plenty for a chart and keep the page light.
                recent = prices.iloc[-504:]
                step = max(1, len(recent) // 400)
                for date, close in recent["close"].iloc[::step].items():
                    value = sma.get(date)
                    chart.append({"d": date.date().isoformat(), "p": round(float(close), 4),
                                  "s": None if pd.isna(value) else round(float(value), 4)})
                monthly = prices["close"].iloc[-252:].resample("ME").last().dropna()
                table = [{"date": d.date(), "close": float(v)} for d, v in monthly.items()]
        received = [r for r in received_dividends(session) if r.isin == isin]
    return _render(
        request, "stock.html",
        signal=signal, position=signal.position, result=signal.result, metrics=signal.metrics,
        analysis=analysis, chart=chart, table=table, received=received,
    )


# --- Dividends -------------------------------------------------------------

@router.get("/dividends", response_class=HTMLResponse)
def dividends_page(request: Request, year: int | None = None, month: int | None = None):
    today = dt.date.today()
    year = year if year and 1990 <= year <= 2100 else today.year
    month = month if month and 1 <= month <= 12 else today.month
    with session_scope(_factory(request)) as session:
        received = received_dividends(session)
        expected = expected_dividends(session, today=today)
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

@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    with session_scope(_factory(request)) as session:
        status = import_status(session)
    return _render(request, "import.html", status=status, preview=None, error=None, done=request.query_params.get("done"))


@router.post("/import", response_class=HTMLResponse)
async def import_preview(request: Request, file: UploadFile = File(...)):
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    with session_scope(_factory(request)) as session:
        status = import_status(session)
        if len(raw) > MAX_UPLOAD_BYTES:
            return _render(request, "import.html", status=status, preview=None, error=T["imp_too_large"], done=None)
        try:
            parsed = parse_export(raw)
        except UnknownFormat as exc:
            return _render(request, "import.html", status=status, preview=None, error=str(exc), done=None)
        check = check_duplicates(session, parsed)
    rows = parsed.transactions if parsed.kind == "transactions" else parsed.entries
    dates = [r.date for r in rows]
    token = token_hex(16)
    (request.app.state.config.upload_dir / f"{token}.upload").write_bytes(raw)
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
    return _render(request, "import.html", status=status, preview=preview, error=None, done=None)


def _upload_path(request: Request, token: str) -> Path | None:
    if not TOKEN_RE.match(token):
        return None
    return request.app.state.config.upload_dir / f"{token}.upload"


@router.post("/import/confirm", response_class=HTMLResponse)
def import_confirm(request: Request, token: str = Form(...)):
    path = _upload_path(request, token)
    if path is None or not path.exists():
        with session_scope(_factory(request)) as session:
            status = import_status(session)
        return _render(request, "import.html", status=status, preview=None, error=T["imp_expired"], done=None)
    parsed = parse_export(path.read_bytes())
    with session_scope(_factory(request)) as session:
        added = save_export(session, parsed)
    path.unlink(missing_ok=True)
    _start_refresh(request)
    return RedirectResponse(f"/import?done={added}", status_code=303)


@router.post("/import/cancel")
def import_cancel(request: Request, token: str = Form(...)):
    path = _upload_path(request, token)
    if path is not None:
        path.unlink(missing_ok=True)
    return RedirectResponse("/import", status_code=303)


# --- Settings --------------------------------------------------------------

def _settings_context(session) -> dict:
    products = session.scalars(select(Product).order_by(Product.name)).all()
    last_dates = dict(session.execute(select(Price.ticker, func.max(Price.date)).group_by(Price.ticker)).all())
    return {
        "analysis": get_analysis_settings(session),
        "factors": FACTORS,
        "products": products,
        "last_dates": last_dates,
        "status": refresh_status(session),
    }


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    with session_scope(_factory(request)) as session:
        context = _settings_context(session)
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
            set_setting(session, "analysis", values)
            bump_data_version(session)
        else:
            context = _settings_context(session)
    if error is None:
        return RedirectResponse("/settings?saved=1", status_code=303)
    return _render(request, "settings.html", saved=False, error=T["set_invalid"].format(error=error), **context)


@router.post("/settings/ticker")
def settings_ticker(request: Request, isin: str = Form(...), ticker: str = Form("")):
    if TICKER_RE.match(ticker.strip()):
        with session_scope(_factory(request)) as session:
            if session.get(Product, isin) is not None:
                set_manual_ticker(session, isin, ticker)
    return RedirectResponse("/settings?saved=1", status_code=303)


# --- Backtest --------------------------------------------------------------

def _run_backtest_job(factory) -> None:
    try:
        with session_scope(factory) as session:
            analysis = get_analysis_settings(session)
            tickers = [p for p in session.scalars(select(Product.ticker).where(Product.ticker.is_not(None)))]
            portfolio, _, _ = compute_signals(session)
            held = {p.ticker for p in portfolio.positions if p.ticker}
            prices = {t: load_prices(session, t)["adj_close"] for t in tickers if t in held}
            prices = {t: s for t, s in prices.items() if not s.empty}
            bench_frame = load_prices(session, analysis["benchmark"])
        benchmark = bench_frame["adj_close"] if not bench_frame.empty else None
        result = run_backtest(prices, benchmark, analysis)
        if result is not None:
            result.pop("signals", None)
        with session_scope(factory) as session:
            set_setting(session, "backtest", {
                "state": "done", "finished": dt.datetime.now().isoformat(), "result": result,
            })
    except Exception as exc:
        log.exception("Backtest failed")
        with session_scope(factory) as session:
            set_setting(session, "backtest", {"state": "failed", "error": str(exc)[:500]})
    finally:
        _backtest_lock.release()


@router.get("/backtest", response_class=HTMLResponse)
def backtest_page(request: Request):
    with session_scope(_factory(request)) as session:
        stored = get_setting(session, "backtest", None)
    running = _backtest_lock.locked()
    return _render(request, "backtest.html", backtest=stored, running=running)


@router.post("/backtest/run")
def backtest_run(request: Request):
    if _backtest_lock.acquire(blocking=False):
        threading.Thread(target=_run_backtest_job, args=(_factory(request),), daemon=True, name="backtest").start()
    return RedirectResponse("/backtest", status_code=303)
