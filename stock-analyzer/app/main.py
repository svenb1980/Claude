"""Application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import user_count
from app.config import Config, load_config
from app.db import make_engine, make_session_factory, session_scope
from app.market.provider import get_provider
from app.market.refresh import refresh_all
from app.market.screener_refresh import refresh_batch, seed_universe
from app.migrations import migrate
from app.models import User
from app.scheduler import start_scheduler
from app.web.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PUBLIC_PATHS = ("/login", "/setup", "/healthz", "/static/")


def create_app(config: Config | None = None, provider=None, seed: bool = True) -> FastAPI:
    config = config or load_config()
    engine = make_engine(config.db_path)
    migrate(engine)
    factory = make_session_factory(engine)
    if seed:
        with session_scope(factory) as session:
            seed_universe(session)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = None
        if config.scheduler_enabled:
            def nightly():
                refresh_all(factory, app.state.get_provider())
                refresh_batch(factory, app.state.get_provider(), config.screener_batch)

            scheduler = start_scheduler(nightly, config.refresh_hour, config.timezone)
        yield
        if scheduler:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Aandelen-analyzer", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.config = config
    app.state.session_factory = factory

    cached_provider = {"value": provider}

    def _get_provider():
        # Created on first use, so the app also starts when the market source is broken.
        if cached_provider["value"] is None:
            cached_provider["value"] = get_provider(config.market_provider)
        return cached_provider["value"]

    app.state.get_provider = _get_provider

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Reject form posts sent from another site to this tool.
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return PlainTextResponse("Verzoek van een andere site geweigerd.", status_code=403)
        path = request.url.path
        request.state.user = None
        with session_scope(factory) as session:
            has_users = user_count(session) > 0
            user_id = request.session.get("user_id")
            user = session.get(User, user_id) if user_id else None
            if user is not None and request.session.get("sv") == user.session_version:
                request.state.user = user
        if path.startswith(PUBLIC_PATHS):
            return await call_next(request)
        if not has_users:
            return RedirectResponse("/setup", status_code=303)
        if request.state.user is None:
            request.session.clear()
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    # Added after `guard`, so it runs first and request.session is available there.
    app.add_middleware(SessionMiddleware, secret_key=config.secret_key, same_site="lax", https_only=False)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
    app.include_router(router)
    return app


app = create_app()
