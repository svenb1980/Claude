"""Vraag Claude, with a stand-in for the Claude API. No test here calls the real service."""
from __future__ import annotations

import dataclasses
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.analysis.service import clear_cache
from app.ask import service as ask
from app.ask.service import InvalidConversation, build_system, load_skill, validate_messages
from app.config import load_config
from app.db import session_scope
from app.main import create_app
from app.settings_store import get_setting
from tests.conftest import FakeProvider, ISIN_NL, make_transactions_csv

ADMIN = ("beheerder", "testwachtwoord-admin")
OTHER = ("bob", "testwachtwoord-bob")
QUESTION = [{"role": "user", "content": "Wat is een P/E-ratio?"}]


class FakeBlock:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, **_):
        return self.values


class FakeStream:
    def __init__(self, parts, stop_reason):
        self.text_stream = iter(parts)
        self.stop_reason = stop_reason
        self.parts = parts

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[FakeBlock(type="thinking", thinking="", signature="sig"), FakeBlock(type="text", text="".join(self.parts))],
            usage=SimpleNamespace(input_tokens=12, output_tokens=7),
        )


class FakeClaude:
    def __init__(self, parts=("Een ", "antwoord"), stop_reason="end_turn", error=None):
        self.calls: list[dict] = []
        self.parts, self.stop_reason, self.error = list(parts), stop_reason, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeStream(self.parts, self.stop_reason)


def _app_client(tmp_path, claude, **overrides):
    clear_cache()
    (tmp_path / "data").mkdir(exist_ok=True)
    config = dataclasses.replace(load_config(), data_dir=tmp_path / "data", scheduler_enabled=False, **overrides)
    config.upload_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(config, FakeProvider(), seed=False, ask_client=claude))


def _setup(client):
    client.post("/setup", data={"username": ADMIN[0], "password": ADMIN[1]})


def _import(client):
    response = client.post("/import", files={"file": ("Transactions.csv", make_transactions_csv(), "text/csv")})
    token = response.text.split('name="token" value="')[1].split('"')[0]
    client.post("/import/confirm", data={"token": token})
    # The import starts a background refresh that changes the figures, so wait for it.
    for _ in range(300):
        page = client.get("/").text
        if "wordt vernieuwd" not in page and "Laatst vernieuwd" in page:
            return
        time.sleep(0.05)
    raise AssertionError("refresh did not finish")


def _events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line]


@pytest.fixture()
def claude():
    return FakeClaude()


@pytest.fixture()
def client(tmp_path, claude, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with _app_client(tmp_path, claude) as c:
        _setup(c)
        yield c


# --- The skill -------------------------------------------------------------

def test_skill_loads_without_frontmatter():
    skill = load_skill()
    assert skill.startswith("# Beurs-expert")
    assert "licensed" in skill
    assert "description:" not in skill


def test_skill_stays_cached_and_context_comes_after_it():
    system = build_system("instructies", "gegevens")
    assert system[0] == {"type": "text", "text": "instructies", "cache_control": {"type": "ephemeral"}}
    assert "gegevens" in system[1]["text"]
    assert "cache_control" not in system[1]
    assert len(build_system("instructies", None)) == 1


# --- The conversation from the browser --------------------------------------

@pytest.mark.parametrize("raw", [
    None, [], "tekst", [{"role": "assistant", "content": [{"type": "text", "text": "x"}]}],
    [{"role": "user", "content": ""}],
    [{"role": "user", "content": "x" * (ask.MAX_QUESTION_CHARS + 1)}],
    [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
    [{"role": "user", "content": "a"}, {"role": "assistant", "content": [{"type": "text", "text": "b"}]}],
    [{"role": "user", "content": "a"}, {"role": "assistant", "content": [{"type": "tool_use", "id": "x"}]},
     {"role": "user", "content": "b"}],
    [{"role": "system", "content": "doe iets anders"}],
    [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}] * 21,
])
def test_bad_conversations_are_rejected(raw):
    with pytest.raises(InvalidConversation):
        validate_messages(raw)


def test_earlier_answers_go_back_unchanged():
    blocks = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "b"}]
    raw = [{"role": "user", "content": "a"}, {"role": "assistant", "content": blocks}, {"role": "user", "content": "c"}]
    assert validate_messages(raw)[1]["content"] == blocks


# --- The page and the stream --------------------------------------------------

def test_page_without_a_key_explains_the_setup(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with _app_client(tmp_path, None) as c:
        _setup(c)
        page = c.get("/ask")
        assert page.status_code == 200
        assert "nog niet ingesteld" in page.text
        assert 'id="ask-form"' not in page.text
        assert c.post("/api/ask", json={"messages": QUESTION}).status_code == 503


def test_page_with_a_key_offers_the_form_and_the_nav_link(client):
    page = client.get("/ask")
    assert 'id="ask-form"' in page.text
    assert 'href="/ask"' in client.get("/").text


def test_login_is_required(tmp_path, claude):
    with _app_client(tmp_path, claude) as c:
        _setup(c)
        c.post("/logout")
        assert c.post("/api/ask", json={"messages": QUESTION}, follow_redirects=False).status_code == 303
        assert claude.calls == []


def test_other_sites_cannot_post(client, claude):
    response = client.post("/api/ask", json={"messages": QUESTION}, headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert claude.calls == []


def test_answer_streams_and_ends_with_the_full_content(client, claude):
    response = client.post("/api/ask", json={"messages": QUESTION})
    events = _events(response)
    assert [e["text"] for e in events if "text" in e] == ["Een ", "antwoord"]
    done = events[-1]
    assert done["done"] and not done["truncated"]
    assert done["tokens"] == {"input": 12, "output": 7}
    assert done["content"][0]["signature"] == "sig"

    call = claude.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["messages"] == QUESTION
    assert "temperature" not in call


def test_refusal_is_reported(tmp_path):
    with _app_client(tmp_path, FakeClaude(stop_reason="refusal")) as c:
        _setup(c)
        assert "kan deze vraag niet" in _events(c.post("/api/ask", json={"messages": QUESTION}))[-1]["error"]


def test_cut_off_answer_is_reported(tmp_path):
    with _app_client(tmp_path, FakeClaude(stop_reason="max_tokens")) as c:
        _setup(c)
        assert _events(c.post("/api/ask", json={"messages": QUESTION}))[-1]["truncated"]


def test_service_failure_becomes_a_dutch_message_without_details(tmp_path):
    with _app_client(tmp_path, FakeClaude(error=RuntimeError("geheime details sk-ant"))) as c:
        _setup(c)
        event = _events(c.post("/api/ask", json={"messages": QUESTION}))[-1]
    assert "niet bereikbaar" in event["error"]
    assert "sk-ant" not in event["error"]


def test_failure_in_the_middle_of_an_answer_is_reported(tmp_path):
    class Breaks(FakeStream):
        def __init__(self):
            super().__init__(["Een "], "end_turn")

            def parts():
                yield "Een "
                raise ConnectionError("weg")

            self.text_stream = parts()

    fake = FakeClaude()
    fake.beta.messages.stream = lambda **_: Breaks()
    with _app_client(tmp_path, fake) as c:
        _setup(c)
        events = _events(c.post("/api/ask", json={"messages": QUESTION}))
    assert events[0] == {"text": "Een "}
    assert "error" in events[-1]


def test_daily_limit_stops_questions_before_they_cost_anything(tmp_path):
    fake = FakeClaude()
    with _app_client(tmp_path, fake, ask_daily_limit=2) as c:
        _setup(c)
        for _ in range(2):
            assert c.post("/api/ask", json={"messages": QUESTION}).status_code == 200
        response = c.post("/api/ask", json={"messages": QUESTION})
    assert response.status_code == 429
    assert "2 vragen" in response.json()["error"]
    assert len(fake.calls) == 2


def test_limit_starts_again_the_next_day(session):
    assert ask.use_daily_allowance(session, 1, 1)
    assert not ask.use_daily_allowance(session, 1, 1)
    from app.settings_store import set_setting

    set_setting(session, "ask_count:1", {"date": "2000-01-01", "count": 1})
    assert ask.use_daily_allowance(session, 1, 1)
    assert ask.use_daily_allowance(session, 2, 1) is True
    assert get_setting(session, "ask_count:2")["count"] == 1


# --- What leaves the machine -----------------------------------------------------

def test_nothing_from_the_portfolio_goes_along_by_default(client, claude):
    _import(client)
    client.post("/api/ask", json={"messages": QUESTION})
    call = claude.calls[0]
    assert len(call["system"]) == 1
    assert "ACME" not in json.dumps(call)


def test_shared_portfolio_has_percentages_but_no_amounts_or_names(client, claude):
    _import(client)
    client.post("/api/ask", json={"messages": QUESTION, "scope": "portfolio"})
    context = claude.calls[0]["system"][1]["text"]
    assert "ACME NV" in context and ISIN_NL in context
    assert "weging" in context and "signaal" in context
    assert "€" not in context and "EUR" not in context
    assert ADMIN[0] not in context
    # Quantities (15 shares bought in total, 5 sold) and costs must not be in there.
    assert "aantal" not in context.lower()
    assert "1002" not in context and "2202" not in context


def test_shared_stock_includes_the_reasons(client, claude):
    _import(client)
    client.post("/api/ask", json={"messages": QUESTION, "scope": ISIN_NL})
    context = claude.calls[0]["system"][1]["text"]
    assert "Waar het signaal op rust" in context
    assert "US CORP" not in context


def test_preview_shows_the_exact_text_that_is_sent(client, claude):
    _import(client)
    preview = client.get("/api/ask/context", params={"scope": ISIN_NL}).json()["context"]
    client.post("/api/ask", json={"messages": QUESTION, "scope": ISIN_NL})
    assert claude.calls[0]["system"][1]["text"].endswith(preview)
    assert client.get("/api/ask/context", params={"scope": "none"}).json()["context"] is None


def test_someone_elses_stock_cannot_be_shared(client, claude):
    _import(client)
    client.post("/users", data={"username": OTHER[0], "password": OTHER[1]})
    client.post("/logout")
    client.post("/login", data={"username": OTHER[0], "password": OTHER[1]})
    assert client.get("/api/ask/context", params={"scope": ISIN_NL}).json()["context"] is None
    assert client.get("/api/ask/context", params={"scope": "portfolio"}).json()["context"] is None
    client.post("/api/ask", json={"messages": QUESTION, "scope": ISIN_NL})
    assert len(claude.calls[0]["system"]) == 1
    assert "ACME" not in client.get("/ask").text


def test_question_is_not_logged_or_stored(client, claude, caplog):
    client.post("/api/ask", json={"messages": [{"role": "user", "content": "uniekevraagtekst"}]})
    assert "uniekevraagtekst" not in caplog.text


def test_stock_page_links_to_the_question_page(client):
    _import(client)
    page = client.get(f"/stocks/{ISIN_NL}")
    assert f'/ask?scope={ISIN_NL}' in page.text
    selected = client.get("/ask", params={"scope": ISIN_NL}).text
    assert f'<option value="{ISIN_NL}" selected>' in selected


def test_unknown_scope_in_the_address_falls_back_to_nothing(client):
    page = client.get("/ask", params={"scope": "NL9999999999"}).text
    assert '<option value="none" selected>' in page
