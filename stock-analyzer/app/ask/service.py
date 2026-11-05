"""Vraag Claude: sends a question to Claude and streams the answer back.

There are two ways to reach Claude. By default the app runs Claude Code on this computer, which uses
the owner's Claude subscription, so only that one account may use it. With ASK_BACKEND=api it uses
the Claude API and an API key instead, billed per question, and every account may use it.

Conversations are not stored on the server. They live in the browser tab, and nothing about a
question is logged. Portfolio data only goes along when the user picks it for that question, and
then only as percentages, labels and reasons: never amounts, quantities or the user's name.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.service import Signal, compute_signals
from app.i18n.nl import T
from app.models import User
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
BACKEND_CLAUDE_CODE = "claude-code"
BACKEND_API = "api"
CLI_TIMEOUT_SECONDS = 180
# Claude Code can normally run commands and edit files. Here it may only write an answer: no tools,
# no MCP servers, no skills, no settings or project files, and nothing saved between questions.
CLI_FLAGS = [
    "-p", "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
    "--no-session-persistence", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
]


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


# --- Claude Code, with the owner's subscription --------------------------------

def owner_id(session: Session) -> int | None:
    """The account whose Claude subscription this is: the oldest administrator."""
    return session.scalar(select(User.id).where(User.is_admin.is_(True)).order_by(User.id).limit(1))


def find_cli(configured: str = "") -> list[str] | None:
    """How to start Claude Code, or None if it isn't installed."""
    if configured:
        return [configured]
    found = shutil.which("claude")
    if found:
        return [found]
    for name in ("claude.exe", "claude"):
        candidate = Path.home() / ".local" / "bin" / name
        if candidate.exists():
            return [str(candidate)]
    return None


def cli_env() -> dict[str, str]:
    """This process's environment, without anything that would move Claude Code off the subscription.

    An API key in the environment would otherwise take priority and be billed per question.
    """
    return {
        name: value for name, value in os.environ.items()
        if name == "CLAUDE_CONFIG_DIR" or not name.upper().startswith(("ANTHROPIC", "CLAUDE"))
    }


def _block_text(content) -> str:
    return "".join(block.get("text", "") for block in content if block.get("type") == "text")


def cli_prompt(messages: list[dict], context: str | None) -> str:
    """Claude Code gets the whole conversation as text, because no session is kept between questions."""
    parts = []
    if context:
        parts.append("App data, shared by the user for this question:\n\n" + context)
    if len(messages) > 1:
        turns = [
            ("User: " + m["content"]) if m["role"] == "user" else ("You: " + _block_text(m["content"]))
            for m in messages[:-1]
        ]
        parts.append("Earlier in this conversation:\n\n" + "\n\n".join(turns))
        parts.append("New question: " + messages[-1]["content"])
    else:
        parts.append(messages[-1]["content"])
    return "\n\n".join(parts)


def _cli_error_text(result: dict) -> str:
    message = str(result.get("result", "")).lower()
    status = result.get("api_error_status")
    if status in (401, 403) or "authenticate" in message or "log in" in message or "login" in message:
        return T["ask_cli_login"]
    if status == 429 or "limit" in message:
        return T["ask_cli_limit"]
    return T["ask_error_service"]


def stream_cli(
    command: list[str], workdir: Path, model: str, skill: str, context: str | None, messages: list[dict],
) -> Iterator[dict]:
    """Same events as stream_answer. The question goes over stdin, so it isn't in the process list."""
    args = [*command, *CLI_FLAGS, "--system-prompt", skill]
    if model:
        args += ["--model", model]
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        process = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=workdir,
            env=cli_env(), encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        log.warning("Claude Code start niet: %s", type(exc).__name__)
        yield {"error": T["ask_not_ready"]}
        return

    timer = threading.Timer(CLI_TIMEOUT_SECONDS, process.kill)
    timer.start()
    written: list[str] = []
    result = None
    try:
        try:
            process.stdin.write(cli_prompt(messages, context))
            process.stdin.close()
        except OSError:
            pass  # It stopped early. What it reported is read below.
        for line in process.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "stream_event":
                inner = event.get("event", {})
                delta = inner.get("delta", {})
                if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                    written.append(delta["text"])
                    yield {"text": delta["text"]}
            elif event.get("type") == "result":
                result = event
        process.wait()
    finally:
        # Also runs when the browser goes away in the middle of an answer.
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()

    if result is None:
        log.warning("Claude Code gaf geen resultaat, code %s", process.returncode)
        yield {"error": T["ask_error_service"]}
        return
    if result.get("is_error"):
        log.warning("Claude Code meldt een fout, status %s", result.get("api_error_status"))
        yield {"error": _cli_error_text(result)}
        return
    if result.get("stop_reason") == "refusal":
        yield {"error": T["ask_refused"]}
        return
    text = "".join(written)
    if not text:
        text = str(result.get("result") or "")
        if not text:
            yield {"error": T["ask_error_service"]}
            return
        yield {"text": text}
    yield {
        "done": True,
        "content": [{"type": "text", "text": text}],
        "truncated": result.get("stop_reason") == "max_tokens",
    }
