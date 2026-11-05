"""Rebuild app/market/universe.json, the stock list the screener searches.

Run now and then, because index memberships change:

    python scripts/build_universe.py

Source: Wikipedia's constituent tables. Europe is covered by national large and mid cap
indices, because no free STOXX Europe 600 list could be retrieved reliably. Tickers are
converted to Yahoo's format. A ticker Yahoo doesn't recognise is harmless: the screener
reports it and moves on. An index that fails keeps its stocks from the existing file.
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

HEADERS = {"User-Agent": "stock-analyzer-universe-builder/1.0 (personal, low-volume use)"}
OUTPUT = Path(__file__).resolve().parent.parent / "app" / "market" / "universe.json"
WIKI = "https://en.wikipedia.org/wiki/"
PAUSE_SECONDS = 6

# (label, page, Yahoo suffix for tickers without one)
INDICES = [
    ("AEX", "AEX_index", ".AS"),
    ("AMX", "AMX_index", ".AS"),
    ("BEL 20", "BEL_20", ".BR"),
    ("DAX", "DAX", ".DE"),
    ("MDAX", "MDAX", ".DE"),
    ("CAC 40", "CAC_40", ".PA"),
    ("SBF 120", "SBF_120", ".PA"),
    ("FTSE 100", "FTSE_100_Index", ".L"),
    ("FTSE 250", "FTSE_250_Index", ".L"),
    ("SMI", "Swiss_Market_Index", ".SW"),
    ("IBEX 35", "IBEX_35", ".MC"),
    ("FTSE MIB", "FTSE_MIB", ".MI"),
    ("OMXS30", "OMX_Stockholm_30", ".ST"),
    ("OMXH25", "OMX_Helsinki_25", ".HE"),
    ("OMXC25", "OMX_Copenhagen_25", ".CO"),
    ("OBX", "OBX_Index", ".OL"),
    ("S&P 500", "List_of_S%26P_500_companies", ""),
]
TICKER_COLUMNS = ("ticker", "symbol", "ticker symbol", "epic", "tidm", "ticker symbol[1]")
NAME_COLUMNS = ("company", "security", "name", "constituent")
YAHOO_SUFFIX_RE = re.compile(r"\.[A-Z]{1,2}$")


def fetch(url: str) -> str:
    for attempt in range(3):
        response = requests.get(url, headers=HEADERS, timeout=60)
        if response.status_code not in (403, 429):
            response.raise_for_status()
            return response.text
        time.sleep(30 * (attempt + 1))  # Asked to slow down, so do.
    response.raise_for_status()
    return response.text


def to_yahoo(raw: str, suffix: str) -> str | None:
    symbol = raw.strip().split(":")[-1].strip().upper()
    symbol = re.sub(r"\[.*?\]", "", symbol).strip()
    if not symbol or symbol == "NAN" or len(symbol) > 14:
        return None
    if suffix and symbol.endswith(suffix.upper()):
        return symbol
    if suffix and YAHOO_SUFFIX_RE.search(symbol) and symbol[-2:] not in (".A", ".B"):
        return symbol  # The table already gives a Yahoo-style ticker.
    symbol = symbol.rstrip(".").replace(" ", "-").replace(".", "-")
    return symbol + suffix


def load_index(page: str, suffix: str, label: str) -> list[dict]:
    best: list[dict] = []
    for table in pd.read_html(io.StringIO(fetch(WIKI + page))):
        columns = {str(c).strip().lower(): c for c in table.columns}
        ticker_col = next((columns[c] for c in TICKER_COLUMNS if c in columns), None)
        if ticker_col is None:
            continue
        name_col = next((columns[c] for c in NAME_COLUMNS if c in columns), None)
        rows = []
        for _, row in table.iterrows():
            ticker = to_yahoo(str(row[ticker_col]), suffix)
            if ticker:
                name = str(row[name_col]).strip() if name_col is not None else ""
                rows.append({"ticker": ticker, "name": name, "index": label})
        if len(rows) > len(best):
            best = rows
    return best


def main() -> int:
    previous = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else []
    merged: dict[str, dict] = {}

    def add(ticker: str, name: str, label: str) -> None:
        entry = merged.setdefault(ticker, {"ticker": ticker, "name": name, "indices": []})
        if label not in entry["indices"]:
            entry["indices"].append(label)

    for label, page, suffix in INDICES:
        try:
            rows = load_index(page, suffix, label)
            if not rows:
                raise ValueError("no ticker table found")
            print(f"{label}: {len(rows)} stocks")
            for row in rows:
                add(row["ticker"], row["name"], label)
        except Exception as exc:
            kept = [s for s in previous if label in s.get("indices", [])]
            print(f"{label}: FAILED ({exc}); keeping {len(kept)} from the existing file", file=sys.stderr)
            for stock in kept:
                add(stock["ticker"], stock["name"], label)
        time.sleep(PAUSE_SECONDS)

    if not merged:
        print("Nothing retrieved; existing file unchanged.", file=sys.stderr)
        return 1
    stocks = sorted(merged.values(), key=lambda s: s["ticker"])
    OUTPUT.write_text(json.dumps(stocks, indent=0, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(stocks)} stocks to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
