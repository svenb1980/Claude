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

from app.config import Config, load_config
from app.db import Base, make_engine, make_session_factory
from app.market.provider import get_provider
from app.market.refresh import refresh_all
from app.scheduler import start_scheduler
from app.web.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PUBLIC_PATHS = ("/login", "/healthz", "/static/")


def create_app(config: Config | None = None, provider=None) -> FastAPI:
    config = config or load_config()
    engine = make_engine(config.db_path)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = None
        if config.scheduler_enabled:
            scheduler = start_scheduler(
                lambda: refresh_all(factory, app.state.get_provider()),
                config.refresh_hour,
                config.timezone,
            )
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
        if config.password and not path.startswith(PUBLIC_PATHS) and not request.session.get("authenticated"):
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    # Added after `guard`, so it runs first and request.session is available there.
    app.add_middleware(SessionMiddleware, secret_key=config.secret_key, same_site="lax", https_only=False)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
    app.include_router(router)
    return app


app = create_app()
