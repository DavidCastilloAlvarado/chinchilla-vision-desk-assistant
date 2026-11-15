import sys
from pathlib import Path

import pytest
from PIL import Image

from chinchilla.core import agent as agent_module
from chinchilla.core import llm, search
from chinchilla.core.thread import Turn
from chinchilla.store import config, session as session_store

FAKE_SERVER = Path(__file__).with_name("fake_mcp_server.py")


class FakeProvider:
    def __init__(self, *scripts):
        self.scripts = list(scripts)
        self.calls = []

    def chat(self, messages, tools=None, stream=True):
        self.calls.append({"messages": list(messages), "tools": tools})
        script = self.scripts.pop(0) if self.scripts else []
        for chunk in script:
            yield chunk


def make_settings(**overrides) -> config.Settings:
    settings = config.default_settings()
    settings.mcp_command = [sys.executable, str(FAKE_SERVER)]
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


@pytest.fixture()
def session(xdg):
    session_store.paths.ensure_dirs()
    return session_store.Session(title="Test")


def test_action_prompt_uses_settings(session):
    settings = make_settings(language="French", level="C1")
    settings.action("translate").prompt = "Translate into {language} for a {level} reader"
    agent = agent_module.Agent(session, settings, provider=FakeProvider())
    turn = agent.prepare_turn(action="translate")
    assert turn.text == "Translate into French for a C1 reader"
    assert turn.action == "translate"


def test_capture_images_are_attached(session):
    capture = session.add_capture(Image.new("RGB", (60, 40), (12, 34, 56)))
    settings = make_settings()
    provider = FakeProvider([llm.Chunk("text", text="ok"), llm.Chunk("done")])
    agent = agent_module.Agent(session, settings, provider=provider)

    turn = agent.prepare_turn(action="explain", capture_ids=[capture.id])
    list(agent.run(turn))

    user_message = provider.calls[0]["messages"][-1]
    assert user_message.role == "user"
    assert user_message.images and user_message.images[0][:2] == b"\xff\xd8"
    assert session.turns[-1].role == "assistant"


def test_tool_loop_collects_sources_and_scrubs_citations(session):
    settings = make_settings(web_enabled=True)
    session.web_enabled = True
    provider = FakeProvider(
        [
            llm.Chunk("tool_call", tool_call=llm.ToolCall("call_1", "search", {"query": "tokens"})),
        ],
        [llm.Chunk("text", text="See [1] and [9]."), llm.Chunk("done")],
    )
    turn = session_store.Turn(role="user", text="why?")
    agent = agent_module.Agent(session, settings, provider=provider)
    events = list(agent.run(turn))

    kinds = [event.type for event in events]
    assert "tool" in kinds and "sources" in kinds and kinds[-1] == "done"
    assert provider.calls[1]["tools"] is not None
    final = session.turns[-1]
    assert final.role == "assistant"
    assert "[1]" in final.text and "[9]" not in final.text
    assert [source.url for source in final.sources] == [
        "https://example.com/tokens",
        "https://example.org/retries",
    ]
    # the tool result goes back to the model as a tool message
    tool_messages = [message for message in provider.calls[1]["messages"] if message.role == "tool"]
    assert tool_messages and tool_messages[0].tool_call_id == "call_1"


def test_tools_are_not_offered_when_web_is_off(session):
    settings = make_settings(web_enabled=False)
    provider = FakeProvider([llm.Chunk("text", text="hi"), llm.Chunk("done")])
    agent = agent_module.Agent(session, settings, provider=provider)
    list(agent.run(session_store.Turn(role="user", text="hello")))
    assert provider.calls[0]["tools"] is None


def test_unavailable_search_is_reported_and_turn_still_answers(session):
    settings = make_settings(web_enabled=True, mcp_command=["missing-binary", "mcp"])
    session.web_enabled = True
    provider = FakeProvider([llm.Chunk("text", text="plain answer"), llm.Chunk("done")])
    agent = agent_module.Agent(session, settings, provider=provider)
    events = list(agent.run(Turn(role="user", text="question")))
    notices = [event for event in events if event.type == "notice"]
    assert notices and "unavailable" in notices[0].text
    assert session.turns[-1].text == "plain answer"


def test_provider_errors_are_reported_and_saved(session):
    class Failing:
        def chat(self, messages, tools=None, stream=True):
            raise llm.ProviderError("openai: HTTP 401 bad key")
            yield

    settings = make_settings()
    agent = agent_module.Agent(session, settings, provider=Failing())
    events = list(agent.run(Turn(role="user", text="hello")))
    assert events[0].type == "error"
    assert session.turns[-1].error is True
    assert "bad key" in session.turns[-1].text


def test_session_is_persisted_after_a_turn(session):
    settings = make_settings()
    provider = FakeProvider([llm.Chunk("text", text="saved"), llm.Chunk("done")])
    agent = agent_module.Agent(session, settings, provider=provider)
    list(agent.run(Turn(role="user", text="please save")))
    reloaded = session_store.Session.load(session.id)
    assert reloaded is not None
    assert reloaded.turns[-1].text == "saved"


def test_search_budget_is_enforced(session, monkeypatch):
    settings = make_settings(web_enabled=True)
    session.web_enabled = True
    monkeypatch.setattr(search, "MAX_TOOL_CALLS", 1)
    calls = llm.ToolCall("c1", "search", {"query": "a"})
    second = llm.ToolCall("c2", "search", {"query": "b"})
    provider = FakeProvider(
        [llm.Chunk("tool_call", tool_call=calls)],
        [llm.Chunk("tool_call", tool_call=second)],
        [llm.Chunk("text", text="done")],
    )
    agent = agent_module.Agent(session, settings, provider=provider)
    events = list(agent.run(Turn(role="user", text="search twice")))
    notices = [event.text for event in events if event.type == "notice"]
    assert any("budget" in text for text in notices)


def test_text_only_turns_are_sent_without_images(session):
    settings = make_settings()
    provider = FakeProvider([llm.Chunk("text", text="sure"), llm.Chunk("done")])
    agent = agent_module.Agent(session, settings, provider=provider)

    list(agent.run(Turn(role="user", text="just a question")))

    messages = provider.calls[0]["messages"]
    assert messages[-1].text == "just a question"
    assert all(not message.images for message in messages)


def test_newest_captures_win_the_image_budget(session, monkeypatch):
    monkeypatch.setattr(agent_module, "MAX_IMAGES", 1)
    settings = make_settings()
    session.turns.append(Turn(role="user", text="old cut", captures=[session.add_capture(Image.new("RGB", (30, 20))).id]))
    session.turns.append(Turn(role="assistant", text="old answer"))
    latest = session.add_capture(Image.new("RGB", (40, 25)))
    session.turns.append(Turn(role="user", text="new cut", captures=[latest.id]))
    agent = agent_module.Agent(session, settings, provider=FakeProvider())

    messages = agent.messages(with_web=False)

    users = [message for message in messages if message.role == "user"]
    assert users[0].images == []
    assert "no longer attached" in users[0].text
    assert users[1].images, "the newest cut must keep its image"
