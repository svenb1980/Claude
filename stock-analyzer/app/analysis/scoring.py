"""Turn metrics into factor scores, a total score, a label and readable reasons.

Each input maps to 0-100 through fixed breakpoints, so every number can be traced.
Missing data never counts as neutral: it is left out of the score and lowers the
data coverage. An input that doesn't apply (a P/E for an ETF) doesn't lower coverage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from app.i18n.nl import T

FACTORS = ("trend", "momentum", "risk", "valuation", "quality", "fit")
PRICE_FACTORS = ("trend", "momentum", "risk")
FUND_TYPES = {"ETF", "MUTUALFUND"}


@dataclass
class FactorResult:
    key: str
    score: float | None = None
    coverage: float = 0.0
    applicable: bool = True
    reasons: list[tuple[float, str]] = field(default_factory=list)  # (input score, text)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    total: float | None
    label: str  # sell | hold | buy | insufficient
    confidence: float
    factors: list[FactorResult]
    notes: list[str] = field(default_factory=list)

    @property
    def top_reason(self) -> str | None:
        """The input that sits furthest from neutral, in the heaviest direction."""
        scored = [r for f in self.factors for r in f.reasons]
        if not scored:
            return None
        if self.label == "sell":
            return min(scored, key=lambda r: r[0])[1]
        if self.label == "buy":
            return max(scored, key=lambda r: r[0])[1]
        return max(scored, key=lambda r: abs(r[0] - 50))[1]


def _dutch_decimals(text: str) -> str:
    return re.sub(r"(?<=\d)\.(?=\d)", ",", text)


def _map(value: float, points: list[tuple[float, float]]) -> float:
    xs, ys = zip(*points)
    return float(np.interp(value, xs, ys))


class _Builder:
    def __init__(self, key: str):
        self.result = FactorResult(key=key)
        self._weighted = 0.0
        self._available = 0.0
        self._total = 0.0

    def add(self, value, points, weight, reason_key, missing_key, scale=1.0, **fmt) -> None:
        self._total += weight
        if value is None:
            self.result.missing.append(T[missing_key])
            return
        score = _map(value, points)
        self._weighted += score * weight
        self._available += weight
        self.result.reasons.append((score, _dutch_decimals(T[reason_key].format(v=value * scale, **fmt))))

    def done(self) -> FactorResult:
        if self._total > 0:
            self.result.coverage = self._available / self._total
        if self._available > 0:
            self.result.score = self._weighted / self._available
        return self.result


def score_trend(m: dict) -> FactorResult:
    b = _Builder("trend")
    b.add(m.get("price_vs_sma200"), [(-0.20, 0), (0.20, 100)], 4, "r_price_sma200", "m_price_sma200", 100)
    b.add(m.get("sma50_vs_sma200"), [(-0.10, 0), (0.10, 100)], 3, "r_sma50_sma200", "m_sma50_sma200", 100)
    b.add(m.get("slope_12m"), [(-0.30, 0), (0.30, 100)], 3, "r_slope", "m_slope", 100)
    return b.done()


def score_momentum(m: dict) -> FactorResult:
    b = _Builder("momentum")
    b.add(m.get("r3"), [(-0.15, 0), (0.15, 100)], 2, "r_r3", "m_r3", 100)
    b.add(m.get("r6"), [(-0.25, 0), (0.25, 100)], 2, "r_r6", "m_r6", 100)
    b.add(m.get("r12"), [(-0.35, 0), (0.35, 100)], 3, "r_r12", "m_r12", 100)
    b.add(m.get("relative_12m"), [(-0.25, 0), (0.25, 100)], 3, "r_rs", "m_rs", 100)
    # Very high RSI (overbought) scores lower, just like very low RSI.
    b.add(m.get("rsi"), [(20, 30), (40, 60), (55, 75), (70, 50), (85, 15)], 1, "r_rsi", "m_rsi")
    return b.done()


def score_risk(m: dict) -> FactorResult:
    b = _Builder("risk")
    b.add(m.get("vol_1y"), [(0.10, 100), (0.50, 0)], 3, "r_vol", "m_vol", 100)
    b.add(m.get("max_dd_5y"), [(-0.60, 0), (-0.15, 100)], 3, "r_dd", "m_dd", 100)
    b.add(m.get("sharpe_3y"), [(-0.5, 0), (1.5, 100)], 3, "r_sharpe", "m_sharpe")
    b.add(m.get("beta_3y"), [(0.6, 100), (1.6, 0)], 1, "r_beta", "m_beta")
    return b.done()


def score_valuation(m: dict, f: dict) -> FactorResult:
    b = _Builder("valuation")
    pe = f.get("trailing_pe")
    if pe is not None and pe <= 0:
        pe = None
    b.add(pe, [(10, 100), (40, 0)], 2, "r_pe", "m_pe")
    if m.get("pays_dividend"):
        percentile = m.get("yield_percentile")
        # A high yield against its own past means a relatively low price.
        y = (m.get("yield") or 0) * 100
        b.add(percentile, [(0, 0), (100, 100)], 2, "r_yield_pct", "m_yield", y=y)
    else:
        b.result.notes.append(T["r_no_dividend"])
    return b.done()


def score_quality(m: dict, f: dict) -> FactorResult:
    b = _Builder("quality")
    if m.get("pays_dividend"):
        payout = f.get("payout_ratio")
        b.add(payout, [(0.0, 60), (0.3, 100), (0.6, 90), (1.0, 25), (1.5, 0)], 3, "r_payout", "m_payout", 100)
        b.add(m.get("dividend_streak"), [(0, 20), (10, 100)], 3, "r_streak", "m_streak")
    b.add(f.get("profit_margin"), [(-0.05, 0), (0.25, 100)], 2, "r_margin", "m_margin", 100)
    b.add(f.get("debt_to_equity"), [(30, 100), (300, 0)], 2, "r_debt", "m_debt")
    return b.done()


def score_fit(ctx: dict, analysis: dict) -> FactorResult:
    b = _Builder("fit")
    limit = analysis["max_position_pct"]
    b.add(ctx.get("weight_pct"), [(limit / 2, 100), (limit, 50), (limit * 2, 0)], 3, "r_weight", "m_weight")
    if ctx.get("sector"):
        b.add(ctx.get("sector_pct"), [(25, 100), (50, 30), (80, 0)], 2, "r_sector", "m_sector", name=ctx["sector"])
    # Exposure to the euro is not a currency risk for a euro investor.
    if ctx.get("currency") and ctx["currency"] != "EUR":
        b.add(ctx.get("currency_pct"), [(50, 100), (90, 30)], 1, "r_currency", "m_currency", name=ctx["currency"])
    return b.done()


def _not_applicable(key: str) -> FactorResult:
    return FactorResult(key=key, applicable=False, notes=[T["r_etf"]])


def _combine(factors: list[FactorResult], analysis: dict, ctx: dict | None) -> ScoreResult:
    weights = analysis["weights"]
    score_sum, score_weight, coverage_sum, total_weight = 0.0, 0.0, 0.0, 0.0
    for factor in factors:
        if not factor.applicable:
            continue
        weight = float(weights.get(factor.key, 0))
        total_weight += weight
        coverage_sum += weight * factor.coverage
        if factor.score is not None:
            score_sum += weight * factor.score
            score_weight += weight
    confidence = coverage_sum / total_weight * 100 if total_weight > 0 else 0.0
    total = score_sum / score_weight if score_weight > 0 else None

    notes: list[str] = []
    if total is None or confidence < analysis["min_confidence_pct"]:
        label = "insufficient"
    elif total < analysis["sell_below"]:
        label = "sell"
    elif total >= analysis["buy_from"]:
        label = "buy"
        weight_pct = (ctx or {}).get("weight_pct")
        if weight_pct is not None and weight_pct > analysis["max_position_pct"]:
            label = "hold"
            notes.append(_dutch_decimals(T["r_buy_capped"].format(v=weight_pct, limit=analysis["max_position_pct"])))
    else:
        label = "hold"
    return ScoreResult(total=total, label=label, confidence=confidence, factors=factors, notes=notes)


def score_holding(metrics: dict, fundamentals: dict, ctx: dict, analysis: dict, quote_type: str | None) -> ScoreResult:
    is_fund = (quote_type or "").upper() in FUND_TYPES
    factors = [
        score_trend(metrics),
        score_momentum(metrics),
        score_risk(metrics),
        _not_applicable("valuation") if is_fund else score_valuation(metrics, fundamentals),
        _not_applicable("quality") if is_fund else score_quality(metrics, fundamentals),
        score_fit(ctx, analysis),
    ]
    return _combine(factors, analysis, ctx)


def score_price_only(metrics: dict, analysis: dict) -> ScoreResult:
    """Trend, momentum and risk only, as used by the backtest."""
    factors = [score_trend(metrics), score_momentum(metrics), score_risk(metrics)]
    return _combine(factors, analysis, None)
