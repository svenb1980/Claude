"""User-editable settings, stored in the database."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.models import Setting

DEFAULT_ANALYSIS = {
    # Relative importance of each factor in the total score.
    "weights": {
        "trend": 20,
        "momentum": 15,
        "risk": 15,
        "valuation": 20,
        "quality": 20,
        "fit": 10,
    },
    # Total score below `sell_below` = Verkopen, at or above `buy_from` = Bijkopen.
    "sell_below": 35.0,
    "buy_from": 65.0,
    # A position above this share of the portfolio never gets Bijkopen.
    "max_position_pct": 15.0,
    # Below this data coverage the tool shows "Onvoldoende data" instead of a label.
    "min_confidence_pct": 50.0,
    "risk_free_pct": 2.0,
    "benchmark": "IWDA.AS",
}


def get_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    return json.loads(row.value_json) if row else default


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    payload = json.dumps(value)
    if row:
        row.value_json = payload
    else:
        session.add(Setting(key=key, value_json=payload))
    session.flush()


def get_analysis_settings(session: Session) -> dict:
    merged = deepcopy(DEFAULT_ANALYSIS)
    stored = dict(get_setting(session, "analysis", {}) or {})
    weights = stored.pop("weights", None)
    merged.update(stored)
    if weights:
        merged["weights"].update(weights)
    return merged


def data_version(session: Session) -> int:
    return int(get_setting(session, "data_version", 0))


def bump_data_version(session: Session) -> None:
    set_setting(session, "data_version", data_version(session) + 1)
