"""Rank stocks outside the portfolio with transparent rules.

Inputs are stored per stock by the screener refresh. Scoring happens when the page is
viewed, because weights and portfolio fit differ per user and portfolio.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.scoring import FactorResult, _Builder, _dutch_decimals, score_momentum, score_risk, score_trend
from app.i18n.nl import T
from app.models import ScreenerStock

SCREEN_FACTORS = ("results", "dividend", "valuation", "liquidity", "momentum", "trend", "risk", "spread")

# Each preset is a set of weights over the factors.
PRESETS = {
    "balanced": {"results": 25, "dividend": 10, "valuation": 20, "liquidity": 5, "momentum": 10, "trend": 10, "risk": 10, "spread": 10},
    "results": {"results": 50, "dividend": 0, "valuation": 20, "liquidity": 5, "momentum": 5, "trend": 5, "risk": 5, "spread": 10},
    "dividend": {"results": 15, "dividend": 50, "valuation": 10, "liquidity": 5, "momentum": 0, "trend": 5, "risk": 10, "spread": 5},
    "momentum": {"results": 5, "dividend": 0, "valuation": 0, "liquidity": 10, "momentum": 40, "trend": 30, "risk": 10, "spread": 5},
    "spreading": {"results": 15, "dividend": 5, "valuation": 10, "liquidity": 5, "momentum": 5, "trend": 5, "risk": 15, "spread": 40},
}
CANDIDATE_FROM = 65.0
WEAK_BELOW = 40.0
MIN_CONFIDENCE = 60.0
MAX_CREDIBLE_YIELD = 0.25
MAX_CREDIBLE_GROWTH = 2.0  # Above +200% it's nearly always a low comparison base.
FINANCIAL_SECTOR = "Financial Services"


@dataclass
class ScreenResult:
    ticker: str
    name: str
    sector: str | None
    country: str | None
    currency: str | None
    indices: str
    data_date: str | None
    score: float | None
    confidence: float
    label: str  # candidate | neutral | weak | insufficient
    factors: list[FactorResult]
    top_reasons: list[str]
    dividend_yield: float | None
    trailing_pe: float | None


def _results(f: dict) -> FactorResult:
    b = _Builder("results")
    b.add(f.get("revenue_growth"), [(-0.10, 0), (0.20, 100)], 3, "r_rev_growth", "m_rev_growth", 100)
    growth = f.get("earnings_growth")
    if growth is not None and growth > MAX_CREDIBLE_GROWTH:
        b.result.notes.append(T["r_growth_outlier"].format(v=growth * 100))
        growth = None
    b.add(growth, [(-0.20, 0), (0.30, 100)], 3, "r_eps_growth", "m_eps_growth", 100)
    b.add(f.get("return_on_equity"), [(0.0, 0), (0.25, 100)], 2, "r_roe", "m_roe", 100)
    b.add(f.get("profit_margin"), [(-0.05, 0), (0.25, 100)], 2, "r_margin", "m_margin", 100)
    if f.get("sector") != FINANCIAL_SECTOR:  # Banks run on debt, so the ratio says little.
        b.add(f.get("debt_to_equity"), [(30, 100), (300, 0)], 1, "r_debt", "m_debt")
    return b.done()


def _dividend(m: dict, f: dict) -> FactorResult:
    b = _Builder("dividend")
    if not m.get("pays_dividend"):
        b.result.notes.append(T["r_no_dividend"])
        b.result.score = 0.0
        b.result.coverage = 1.0
        return b.result
    yield_value = m.get("yield")
    if yield_value is not None and yield_value > MAX_CREDIBLE_YIELD:
        # Usually a data error or a one-off payment, and rarely a real yield.
        b.result.notes.append(T["r_yield_suspect"].format(v=yield_value * 100))
        yield_value = None
    b.add(yield_value, [(0.0, 0), (0.05, 100), (0.09, 60)], 3, "r_yield", "m_yield_now", 100)
    b.add(m.get("dividend_streak"), [(0, 20), (10, 100)], 3, "r_streak", "m_streak")
    b.add(f.get("payout_ratio"), [(0.0, 60), (0.3, 100), (0.6, 90), (1.0, 25), (1.5, 0)], 2, "r_payout", "m_payout", 100)
    return b.done()


def _valuation(m: dict, f: dict) -> FactorResult:
    b = _Builder("valuation")
    pe = f.get("trailing_pe")
    forward = f.get("forward_pe")
    b.add(pe if pe and pe > 0 else None, [(10, 100), (40, 0)], 2, "r_pe", "m_pe")
    b.add(forward if forward and forward > 0 else None, [(10, 100), (35, 0)], 2, "r_forward_pe", "m_forward_pe")
    b.add(f.get("price_to_book") if (f.get("price_to_book") or 0) > 0 else None, [(1, 100), (8, 0)], 1, "r_pb", "m_pb")
    if m.get("pays_dividend") and m.get("yield_percentile") is not None:
        b.add(m["yield_percentile"], [(0, 0), (100, 100)], 1, "r_yield_pct", "m_yield", y=(m.get("yield") or 0) * 100)
    return b.done()


def _liquidity(m: dict, f: dict) -> FactorResult:
    """Can you get in and out cheaply? This is the bid-ask side of 'market spread'."""
    b = _Builder("liquidity")
    b.add(f.get("spread_pct"), [(0.05, 100), (1.0, 0)], 3, "r_bid_ask", "m_bid_ask")
    b.add(m.get("turnover_eur_m"), [(0.5, 0), (20, 100)], 2, "r_turnover", "m_turnover")
    return b.done()


def _spread(f: dict, portfolio: dict) -> FactorResult:
    """How much does this add to the portfolio's spread over sectors and countries?"""
    b = _Builder("spread")
    if not portfolio.get("has_positions"):
        b.result.notes.append(T["r_no_portfolio"])
        return b.result
    sector = f.get("sector")
    if sector:
        b.add(portfolio["sectors"].get(sector, 0.0), [(0, 100), (15, 70), (40, 0)], 3, "r_sector_share", "m_sector", name=sector)
    country = f.get("country")
    if country:
        b.add(portfolio["countries"].get(country, 0.0), [(0, 100), (30, 60), (70, 0)], 1, "r_country_share", "m_country", name=country)
    return b.done()


def score_stock(data: dict, portfolio: dict, weights: dict) -> tuple[float | None, float, list[FactorResult]]:
    metrics = data.get("metrics", {})
    fundamentals = data.get("fundamentals", {})
    factors = {
        "results": _results(fundamentals),
        "dividend": _dividend(metrics, fundamentals),
        "valuation": _valuation(metrics, fundamentals),
        "liquidity": _liquidity(metrics, fundamentals),
        "momentum": score_momentum(metrics),
        "trend": score_trend(metrics),
        "risk": score_risk(metrics),
        "spread": _spread(fundamentals, portfolio),
    }
    score_sum, score_weight, coverage, total = 0.0, 0.0, 0.0, 0.0
    ordered = []
    for key in SCREEN_FACTORS:
        factor, weight = factors[key], float(weights.get(key, 0))
        factor.key = key
        ordered.append(factor)
        if weight <= 0 or (key == "spread" and not portfolio.get("has_positions")):
            continue
        total += weight
        coverage += weight * factor.coverage
        if factor.score is not None:
            score_sum += weight * factor.score
            score_weight += weight
    confidence = coverage / total * 100 if total else 0.0
    score = score_sum / score_weight if score_weight else None
    return score, confidence, ordered


def _label(score: float | None, confidence: float) -> str:
    if score is None or confidence < MIN_CONFIDENCE:
        return "insufficient"
    if score >= CANDIDATE_FROM:
        return "candidate"
    return "weak" if score < WEAK_BELOW else "neutral"


def portfolio_profile(positions: list, held_names: set[str] | None = None) -> dict:
    """Sector and country shares of a portfolio in percent."""
    total = sum(p.value_eur for p in positions if p.value_eur is not None)
    sectors: dict[str, float] = {}
    countries: dict[str, float] = {}
    if total > 0:
        for p in positions:
            if p.value_eur is None:
                continue
            if p.sector:
                sectors[p.sector] = sectors.get(p.sector, 0.0) + p.value_eur / total * 100
            if p.country:
                countries[p.country] = countries.get(p.country, 0.0) + p.value_eur / total * 100
    return {
        "has_positions": bool(positions) and total > 0,
        "sectors": sectors,
        "countries": countries,
        "held_tickers": {p.ticker for p in positions if p.ticker},
        "held_isins": {p.isin for p in positions},
        # The same company on another exchange has another ticker but the same name.
        "held_names": {name.lower() for name in (held_names or set()) if name},
    }


def run_screen(session: Session, portfolio: dict, preset: str = "balanced") -> list[ScreenResult]:
    weights = PRESETS.get(preset, PRESETS["balanced"])
    results: list[ScreenResult] = []
    stocks = session.scalars(select(ScreenerStock).where(ScreenerStock.enabled.is_(True),
                                                         ScreenerStock.last_refresh.is_not(None))).all()
    for stock in stocks:
        if stock.ticker in portfolio["held_tickers"] or (stock.isin and stock.isin in portfolio["held_isins"]):
            continue
        if stock.name and stock.name.lower() in portfolio.get("held_names", ()):
            continue
        data = json.loads(stock.data_json or "{}")
        if not data:
            continue
        score, confidence, factors = score_stock(data, portfolio, weights)
        # What pushes this stock up most, counted by weight as well as score.
        ranked = sorted(
            ((reason[0], reason[1]) for f in factors if float(weights.get(f.key, 0)) > 0 for reason in f.reasons),
            key=lambda r: -r[0],
        )
        fundamentals = data.get("fundamentals", {})
        metrics = data.get("metrics", {})
        results.append(ScreenResult(
            ticker=stock.ticker,
            name=stock.name or stock.ticker,
            sector=stock.sector,
            country=stock.country,
            currency=stock.currency,
            indices=stock.indices,
            data_date=metrics.get("last_date"),
            score=score,
            confidence=confidence,
            label=_label(score, confidence),
            factors=factors,
            top_reasons=[_dutch_decimals(text) for _, text in ranked[:3]],
            dividend_yield=metrics.get("yield"),
            trailing_pe=fundamentals.get("trailing_pe"),
        ))
    results.sort(key=lambda r: (r.label == "insufficient", -(r.score or 0)))
    return results
