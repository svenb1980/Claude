"""Market data from Yahoo Finance through the unofficial yfinance library.

It is free but can break or return gaps, so all failures surface as exceptions
that the refresh job records per stock, and cached data keeps being used.
"""
from __future__ import annotations

import datetime as dt
import time

import pandas as pd

from app.market.provider import SymbolMatch

# DEGIRO exchange codes to Yahoo ticker suffixes. An empty suffix means a US listing.
DEGIRO_TO_YAHOO_SUFFIX = {
    "EAM": ".AS", "XET": ".DE", "TDG": ".DE", "FRA": ".F", "EPA": ".PA", "EBR": ".BR",
    "ELI": ".LS", "LSE": ".L", "MIL": ".MI", "MAD": ".MC", "SWX": ".SW", "VIE": ".VI",
    "OMX": ".ST", "OSL": ".OL", "CSE": ".CO", "HEL": ".HE", "TOR": ".TO",
    "NDQ": "", "NSY": "", "ASE": "",
}
ALLOWED_QUOTE_TYPES = {"EQUITY", "ETF", "MUTUALFUND"}
THROTTLE_SECONDS = 0.4


def _to_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _iso(value) -> str | None:
    """Yahoo returns dates as date, datetime or a list of them."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if isinstance(value, (dt.datetime, dt.date)):
        return value.strftime("%Y-%m-%d")
    return None


def _date_index(index: pd.Index) -> list[dt.date]:
    return [ts.date() for ts in pd.DatetimeIndex(index)]


class YFinanceProvider:
    def __init__(self) -> None:
        import yfinance

        self._yf = yfinance

    def _throttle(self) -> None:
        time.sleep(THROTTLE_SECONDS)

    def resolve_isin(self, isin: str, name: str, exchange: str | None) -> SymbolMatch | None:
        self._throttle()
        quotes = self._yf.Search(isin, max_results=10, news_count=0).quotes or []
        quotes = [q for q in quotes if q.get("symbol") and q.get("quoteType") in ALLOWED_QUOTE_TYPES]
        if not quotes:
            return None
        chosen = quotes[0]
        ticker = chosen["symbol"]
        suffix = DEGIRO_TO_YAHOO_SUFFIX.get((exchange or "").upper())
        if suffix is not None:
            for quote in quotes:
                symbol = quote["symbol"]
                if (suffix and symbol.endswith(suffix)) or (not suffix and "." not in symbol):
                    chosen, ticker = quote, symbol
                    break
            else:
                # Yahoo's search often lists one exchange only. Try the same symbol on yours.
                ticker = self._same_symbol_on_exchange(ticker, suffix)
        return SymbolMatch(
            ticker=ticker,
            name=chosen.get("longname") or chosen.get("shortname") or name,
            exchange=chosen.get("exchange"),
            quote_type=chosen.get("quoteType"),
        )

    def _same_symbol_on_exchange(self, ticker: str, suffix: str) -> str:
        if not suffix:
            return ticker
        candidate = ticker.split(".")[0] + suffix
        self._throttle()
        try:
            found = self._yf.Ticker(candidate).history(period="5d")
        except Exception:
            return ticker
        return candidate if found is not None and not found.empty else ticker

    def price_history(self, ticker: str, start: dt.date | None) -> pd.DataFrame:
        self._throttle()
        options = {"start": start.isoformat()} if start else {"period": "max"}
        raw = self._yf.Ticker(ticker).history(auto_adjust=False, actions=False, **options)
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["close", "adj_close", "volume"])
        frame = pd.DataFrame(
            {
                "close": raw["Close"].to_numpy(),
                "adj_close": raw.get("Adj Close", raw["Close"]).to_numpy(),
                "volume": raw["Volume"].to_numpy() if "Volume" in raw else None,
            },
            index=_date_index(raw.index),
        )
        frame = frame.dropna(subset=["close"])
        return frame[~frame.index.duplicated(keep="last")]

    def dividends(self, ticker: str) -> pd.Series:
        self._throttle()
        raw = self._yf.Ticker(ticker).dividends
        if raw is None or raw.empty:
            return pd.Series(dtype=float)
        return pd.Series(raw.to_numpy(), index=_date_index(raw.index), dtype=float)

    def fundamentals(self, ticker: str) -> dict:
        self._throttle()
        handle = self._yf.Ticker(ticker)
        info = handle.info or {}
        data = {
            "name": info.get("longName") or info.get("shortName"),
            "currency": info.get("currency"),
            "quote_type": info.get("quoteType"),
            "sector": info.get("sector"),
            "country": info.get("country"),
            "trailing_pe": _to_float(info.get("trailingPE")),
            "payout_ratio": _to_float(info.get("payoutRatio")),
            "profit_margin": _to_float(info.get("profitMargins")),
            "debt_to_equity": _to_float(info.get("debtToEquity")),
        }
        try:
            calendar = handle.calendar or {}
        except Exception:  # The calendar is often missing for European stocks.
            calendar = {}
        if isinstance(calendar, dict):
            data["next_ex_date"] = _iso(calendar.get("Ex-Dividend Date"))
            data["next_pay_date"] = _iso(calendar.get("Dividend Date"))
        return data

    def fx_history(self, currency: str, start: dt.date | None) -> pd.Series:
        self._throttle()
        options = {"start": start.isoformat()} if start else {"period": "max"}
        raw = self._yf.Ticker(f"{currency}EUR=X").history(auto_adjust=False, actions=False, **options)
        if raw is None or raw.empty:
            return pd.Series(dtype=float)
        series = pd.Series(raw["Close"].to_numpy(), index=_date_index(raw.index), dtype=float).dropna()
        return series[~series.index.duplicated(keep="last")]
