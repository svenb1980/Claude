"""Turn calculated levels into chart lines and readable Dutch evidence."""
from __future__ import annotations

from app.analysis.levels import MIN_EVENTS_FOR_TEXT, Level
from app.i18n.nl import T
from app.web.formatting import number, pct, ratio_pct, signed_ratio_pct

SELL_KEYS = {"stop", "intraday_stop", "s1"}
# Below this difference from a normal period, the level says nothing distinctive.
CLEAR_DIFFERENCE = 0.05


def _daily_text(level: Level) -> str:
    e = level.evidence
    prefix = f'{T["lvl_stop_triggered"]} ' if level.key == "stop" and level.distance_pct > 0 else ""
    if e.events < MIN_EVENTS_FOR_TEXT:
        return prefix + T["lvl_too_few"].format(n=e.events)
    normal = T["lvl_normal"].format(avg=signed_ratio_pct(e.baseline), lower=ratio_pct(e.baseline_lower, 0), days=e.horizon)
    if level.key == "stop":
        text = T["lvl_ev_stop"].format(n=e.events, days=e.horizon, avg=signed_ratio_pct(e.avg_forward), lower=ratio_pct(e.pct_lower, 0))
    else:
        text = T["lvl_ev_ceiling"].format(n=e.events, held=e.held, days=e.horizon, avg=signed_ratio_pct(e.avg_forward), lower=ratio_pct(e.pct_lower, 0))
    return f"{prefix}{text} {normal} {_verdict(e)}"


def _verdict(e) -> str:
    if e.pct_lower is None or e.baseline_lower is None:
        return ""
    difference = e.pct_lower - e.baseline_lower
    if abs(difference) < CLEAR_DIFFERENCE:
        return T["lvl_verdict_none"]
    return T["lvl_verdict_lower"] if difference > 0 else T["lvl_verdict_higher"]


def _intraday_text(level: Level, tested: int) -> str:
    e = level.evidence
    if level.key == "intraday_stop":
        return T["lvl_ev_intraday_stop"]
    if e.events < MIN_EVENTS_FOR_TEXT:
        return T["lvl_too_few"].format(n=e.events)
    template = T["lvl_ev_s1"] if level.key == "s1" else T["lvl_ev_pivot"]
    return template.format(n=e.events, tested=tested, held=e.held)


def _row(level: Level, evidence_text: str) -> dict:
    return {
        "key": level.key,
        "label": T[f"lvl_{level.key}"],
        "explain": T[f"lvl_{level.key}_explain"],
        "price": round(level.price, 4),
        "distance_pct": level.distance_pct,
        "distance": ("+" if level.distance_pct > 0 else "") + pct(level.distance_pct),
        "evidence": evidence_text,
    }


def daily_rows(result: dict) -> list[dict]:
    return [_row(level, _daily_text(level)) for level in result.get("levels", [])]


def intraday_rows(result: dict) -> list[dict]:
    tested = result.get("sessions_tested", 0)
    return [_row(level, _intraday_text(level, tested)) for level in result.get("levels", [])]


def intraday_notes(last_bar: str, age_minutes: int, fee: float, trade_value: float, break_even: float | None, tested: int) -> list[str]:
    notes = [T["intra_last_bar"].format(when=last_bar, age=number(age_minutes, 0))]
    if break_even is not None:
        notes.append(T["intra_break_even"].format(cost=number(fee * 2), value=number(trade_value, 0), pct=number(break_even)))
    notes.append(T["intra_sessions"].format(n=tested))
    return notes


def chart_lines(rows: list[dict]) -> list[dict]:
    """Lines for the chart. The stop is drawn in the second colour, ceilings in the third."""
    lines = []
    for row in rows:
        slot = 2 if row["key"] in SELL_KEYS else 3
        lines.append({"label": row["label"], "price": row["price"], "slot": slot})
    return lines
