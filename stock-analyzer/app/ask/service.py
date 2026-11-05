"""Vraag Claude: sends a question to the Claude API and streams the answer back.

Conversations are not stored on the server. They live in the browser tab, and nothing about a
question is logged. Portfolio data only goes along when the user picks it for that question, and
then only as percentages, labels and reasons: never amounts, quantities or the user's name.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.orm import Session

from app.analysis.service import Signal, compute_signals
from app.i18n.nl import T
from app.settings_store import get_setting, set_setting

log = logging.getLogger(__name__)

SKILL_PATH = Path(__file__).parent / "skills" / "beurs-expert" / "SKILL.md"
SCOPE_NONE = "none"
SCOPE_PORTFOLIO = "portfolio"
MAX_QUESTION_CHARS = 4000
MAX_MESSAGES = 40
MAX_BODY_BYTES = 1024 * 1024
MAX_TOKENS = 16000
# Block types a finished answer can hold. They go back to the API unchanged on the next question.
ASSISTANT_BLOCKS = {"text", "thinking", "redacted_thinking", "fallback"}


class InvalidConversation(ValueError):
    """The browser sent a conversation that can't be a real one."""


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def make_client():
    # Imported here so the rest of the app also works when the feature isn't set up.
    import anthropic

    return anthropic.Anthropic(timeout=180.0)


def load_skill() -> str:
    """The skill's instructions, without the frontmatter."""
    text = SKILL_PATH.read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()


def _pct(value: float | None, decimals: int = 1) -> str:
    return "onbekend" if value is None else f"{value:.{decimals}f}%".replace(".", ",")


def _signal_line(signal: Signal) -> str:
    position, result = signal.position, signal.result
    label = T.get(f"signal_{result.label}", result.label)
    score = "onbekend" if result.total is None else f"{result.total:.0f}/100"
    parts = [
        position.name,
        f"ISIN {position.isin}",
        f"sector {position.sector or 'onbekend'}",
        f"weging {_pct(position.weight_pct)}",
        f"koersresultaat {_pct(position.unrealised_pct)}",
        f"signaal {label}",
        f"score {score}",
        f"datadekking {_pct(result.confidence, 0)}",
    ]
    return "- " + ", ".join(parts)


def _signal_detail(signal: Signal) -> list[str]:
    lines = []
    for factor in signal.result.factors:
        if not factor.applicable:
            continue
        name = T.get(f"factor_{factor.key}", factor.key)
        score = "onbekend" if factor.score is None else f"{factor.score:.0f}/100"
        lines.append(f"{name}: {score}")
        lines.extend(f"  - {text}" for _, text in factor.reasons)
        if factor.missing:
            lines.append("  - Ontbreekt: " + ", ".join(factor.missing))
    lines.extend(f"Opmerking: {note}" for note in signal.result.notes)
    return lines


def scope_options(session: Session, portfolio_id: int, user_id: int) -> list[tuple[str, str]]:
    """The stocks in this user's portfolio that can be shared with a question."""
    _, signals, _ = compute_signals(session, portfolio_id, user_id)
    return [(s.position.isin, s.position.name) for s in sorted(signals, key=lambda s: s.position.name.lower())]


def build_context(session: Session, portfolio_id: int, user_id: int, scope: str) -> str | None:
    """The exact text that goes along with a question, or None if nothing is shared."""
    if scope == SCOPE_NONE:
        return None
    _, signals, _ = compute_signals(session, portfolio_id, user_id)
    today = dt.date.today().isoformat()
    if scope == SCOPE_PORTFOLIO:
        if not signals:
            return None
        lines = [f"Portefeuille op {today}, met per positie de gegevens uit de app:"]
        lines.extend(_signal_line(s) for s in sorted(signals, key=lambda s: -(s.position.weight_pct or 0)))
        return "\n".join(lines)
    signal = next((s for s in signals if s.position.isin == scope), None)
    if signal is None:
        return None
    dated = signal.position.price_date.isoformat() if signal.position.price_date else "onbekend"
    lines = [f"Eén positie op {today} (koers van {dated}):", _signal_line(signal), "Waar het signaal op rust:"]
    lines.extend(_signal_detail(signal))
    return "\n".join(lines)


def build_system(skill: str, context: str | None) -> list[dict]:
    # The skill stays first and cached. The context changes per question, so it comes after it.
    system = [{"type": "text", "text": skill, "cache_control": {"type": "ephemeral"}}]
    if context:
        system.append({"type": "text", "text": "App data, shared by the user for this question:\n\n" + context})
    return system


def validate_messages(raw) -> list[dict]:
    """Checks the conversation from the browser: alternating turns, ending with a new question."""
    if not isinstance(raw, list) or not raw or len(raw) > MAX_MESSAGES:
        raise InvalidConversation("length")
    messages: list[dict] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise InvalidConversation("item")
        role, content = item.get("role"), item.get("content")
        if role != ("user" if index % 2 == 0 else "assistant"):
            raise InvalidConversation("role")
        if role == "user":
            if not isinstance(content, str) or not content.strip() or len(content) > MAX_QUESTION_CHARS:
                raise InvalidConversation("question")
            messages.append({"role": "user", "content": content})
        else:
            if not isinstance(content, list) or not content:
                raise InvalidConversation("answer")
            if not all(isinstance(block, dict) and block.get("type") in ASSISTANT_BLOCKS for block in content):
                raise InvalidConversation("block")
            messages.append({"role": "assistant", "content": content})
    if messages[-1]["role"] != "user":
        raise InvalidConversation("end")
    return messages


def use_daily_allowance(session: Session, user_id: int, limit: int) -> bool:
    """Counts one question for today. False once this user has reached the limit."""
    key = f"ask_count:{user_id}"
    today = dt.date.today().isoformat()
    stored = get_setting(session, key, None) or {}
    count = stored.get("count", 0) if stored.get("date") == today else 0
    if count >= limit:
        return False
    set_setting(session, key, {"date": today, "count": count + 1})
    return True


def _error_text(exc: Exception) -> str:
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return T["ask_error_key"]
    if isinstance(exc, anthropic.PermissionDeniedError):
        return T["ask_error_key"]
    if isinstance(exc, anthropic.NotFoundError):
        return T["ask_error_model"]
    if isinstance(exc, anthropic.RateLimitError):
        return T["ask_error_busy"]
    if isinstance(exc, anthropic.BadRequestError):
        return T["ask_error_conversation"]
    if isinstance(exc, anthropic.APIStatusError):
        return T["ask_error_service"]
    if isinstance(exc, anthropic.APIConnectionError):
        return T["ask_error_connection"]
    return T["ask_error_service"]


def stream_answer(client, model: str, system: list[dict], messages: list[dict]) -> Iterator[dict]:
    """Yields {"text": ...} while Claude writes, then one final event: "done" or "error"."""
    try:
        with client.beta.messages.stream(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for text in stream.text_stream:
                yield {"text": text}
            final = stream.get_final_message()
    except Exception as exc:  # noqa: BLE001 - every failure must reach the page as a message
        log.warning("Vraag Claude mislukt: %s", type(exc).__name__)
        yield {"error": _error_text(exc)}
        return

    if final.stop_reason == "refusal":
        yield {"error": T["ask_refused"]}
        return
    usage = final.usage
    yield {
        "done": True,
        "content": [block.model_dump(mode="json", exclude_none=True) for block in final.content],
        "truncated": final.stop_reason == "max_tokens",
        "tokens": {"input": usage.input_tokens, "output": usage.output_tokens},
    }
