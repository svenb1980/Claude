"""Link DEGIRO's ISINs to the tickers the market data source uses."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market.provider import MarketDataProvider
from app.models import Product
from app.settings_store import bump_data_version


def resolve_missing_symbols(session: Session, provider: MarketDataProvider) -> list[str]:
    """Look up tickers for products without one. Manual choices are left alone."""
    unresolved: list[str] = []
    products = session.scalars(select(Product).where(Product.ticker.is_(None))).all()
    for product in products:
        try:
            match = provider.resolve_isin(product.isin, product.name, product.exchange)
        except Exception as exc:  # A network failure for one stock must not stop the rest.
            product.refresh_error = f"Tickerzoekopdracht mislukt: {exc}"[:500]
            unresolved.append(product.isin)
            continue
        if match is None:
            product.refresh_error = "Geen ticker gevonden. Vul deze handmatig in bij Instellingen."
            unresolved.append(product.isin)
            continue
        product.ticker = match.ticker
        product.ticker_source = "auto"
        product.quote_type = match.quote_type
        product.refresh_error = None
    session.flush()
    return unresolved


def set_manual_ticker(session: Session, isin: str, ticker: str) -> None:
    """Save the user's correction. An empty value hands the choice back to auto lookup."""
    product = session.get(Product, isin)
    if product is None:
        raise ValueError(f"Onbekende ISIN: {isin}")
    cleaned = ticker.strip().upper()
    product.ticker = cleaned or None
    product.ticker_source = "manual" if cleaned else "auto"
    product.refresh_error = None
    product.last_refresh = None
    bump_data_version(session)
    session.flush()
