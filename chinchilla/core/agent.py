"""Turn loop: prompts, images, tool calls and saved turns."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .. import log
from ..store import config, session as session_store
from . import capture as capture_module
from . import llm, prompts, search
from .thread import Source, Turn

LOGGER = log.get("agent")
MAX_ROUNDS = 3
MAX_IMAGES = 4


@dataclass
class AgentEvent:
    type: str  # text | tool | sources | notice | error | done
    text: str = ""
    tool: str = ""
    detail: str = ""
    sources: list[Source] = field(default_factory=list)
    turn: Turn | None = None


class Agent:
    """Runs one user turn against the provider, including tool calls."""

    def __init__(
        self,
        session: session_store.Session,
        settings: config.Settings,
        provider=None,
        search_factory: Callable[[], search.WebSearch] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self._provider = provider
        self._search_factory = search_factory or (lambda: search.WebSearch(settings))
        self._web: search.WebSearch | None = None

    # ---------------------------------------------------------------- helpers

    @property
    def provider(self):
        if self._provider is None:
            self._provider = llm.build_provider(self.settings)
        return self._provider

    def action_prompt(self, action_id: str) -> str:
        action = self.settings.action(action_id)
        if action is None:
            return action_id
        return prompts.render_prompt(action.prompt, self.settings.language, self.settings.level)

    def system_prompt(self, with_web: bool) -> str:
        parts = [prompts.SYSTEM_PROMPT]
        if with_web:
            parts.append(prompts.WEB_PROMPT)
        parts.append(f"The user's language for answers is {self.settings.language}.")
        return "\n\n".join(parts)

    def _image_bytes(self, capture_id: str) -> bytes | None:
        capture = self.session.capture(capture_id)
        if capture is None or not capture.path or not Path(capture.path).is_file():
            return None
        try:
            from PIL import Image

            image = Image.open(capture.path)
            return capture_module.encode_jpeg(image, max_side=self.settings.max_side)
        except Exception as exc:  # pragma: no cover - broken file
            LOGGER.warning("cannot read capture %s: %s", capture.path, exc)
            return None

    def messages(self, with_web: bool) -> list[llm.Message]:
        messages = [llm.Message("system", self.system_prompt(with_web))]
        images_by_turn: dict[int, list[bytes]] = {}
        budget = MAX_IMAGES
        # newest cuts win the budget: an old screenshot is context, the new one is the question
        for index in range(len(self.session.turns) - 1, -1, -1):
            turn = self.session.turns[index]
            if turn.role != "user" or not turn.captures:
                continue
            images: list[bytes] = []
            for capture_id in turn.captures:
                if budget <= 0:
                    break
                data = self._image_bytes(capture_id)
                if data:
                    images.append(data)
                    budget -= 1
            if images:
                images_by_turn[index] = images

        for index, turn in enumerate(self.session.turns):
            if turn.role == "user":
                images = images_by_turn.get(index, [])
                text = turn.text
                if turn.captures and not images:
                    text = f"{text} (the screenshot from this turn is no longer attached)"
                messages.append(llm.Message("user", text, images=images))
            elif turn.text:
                messages.append(llm.Message("assistant", turn.text))
        return messages

    # ------------------------------------------------------------------- turn

    def prepare_turn(
        self,
        text: str | None = None,
        action: str | None = None,
        capture_ids: list[str] | None = None,
    ) -> Turn:
        prompt = text or (self.action_prompt(action) if action else "")
        turn = Turn(role="user", text=prompt, action=action, captures=list(capture_ids or []))
        return turn

    def run(self, turn: Turn) -> Iterator[AgentEvent]:
        if not self.session.turns or self.session.turns[-1] is not turn:
            self.session.add_turn(turn)
        self.session.autotitle(turn.text)
        self.session.provider = self.settings.active().id
        self.session.model = self.settings.active().model

        with_web = bool(self.session.web_enabled and self.settings.mcp_enabled)
        tools: list[llm.ToolSpec] = []
        budget = search.Budget()
        if with_web:
            self._web = self._search_factory()
            if self._web.start():
                tools = self._web.tools()
            else:
                yield AgentEvent(
                    "notice",
                    text=f"web search unavailable: {self._web.error or 'unknown reason'}",
                )
                with_web = False

        messages = self.messages(with_web)
        collected: list[Source] = []
        final_text = ""

        try:
            for _round in range(MAX_ROUNDS):
                round_text = ""
                tool_calls: list[llm.ToolCall] = []
                for chunk in self.provider.chat(messages, tools=tools or None):
                    if chunk.type == "text" and chunk.text:
                        round_text += chunk.text
                        yield AgentEvent("text", text=chunk.text)
                    elif chunk.type == "tool_call" and chunk.tool_call is not None:
                        tool_calls.append(chunk.tool_call)
                final_text += round_text

                if not tool_calls or not with_web:
                    break
                messages.append(
                    llm.Message(
                        "assistant",
                        round_text,
                        tool_calls=[call.as_openai() for call in tool_calls],
                    )
                )
                for call in tool_calls:
                    if not budget.take():
                        yield AgentEvent(
                            "notice",
                            text="search budget reached, answering with what we have",
                        )
                        final_text += "\n\n(stopped searching to stay within budget)"
                        tool_calls = []
                        break
                    yield AgentEvent("tool", tool=call.name, detail=_describe(call))
                    result = self._web.call(call.name, call.arguments) if self._web else None
                    if result is None:
                        continue
                    if result.sources:
                        collected.extend(result.sources)
                    messages.append(
                        llm.Message(
                            "tool",
                            result.text,
                            tool_call_id=call.id,
                            tool_name=call.name,
                        )
                    )
                if not tool_calls:
                    break
            else:
                yield AgentEvent("notice", text="stopped after several tool rounds")
        except llm.ProviderError as exc:
            turn.text = str(exc)
            turn.error = True
            self._persist(turn)
            yield AgentEvent("error", text=str(exc), turn=turn)
            yield AgentEvent("done", turn=turn)
            return
        finally:
            if self._web is not None:
                self._web.close()
                self._web = None

        sources = _unique_sources(collected)
        assistant = Turn(
            role="assistant",
            text=search.scrub_citations(final_text.strip(), sources),
            sources=sources,
        )
        self.session.add_turn(assistant)
        self.session.add_sources(sources)
        self._persist(assistant)
        if sources:
            yield AgentEvent("sources", sources=sources)
        yield AgentEvent("done", turn=assistant)

    def _persist(self, _turn: Turn) -> None:
        if not self.settings.save_sessions:
            return
        try:
            self.session.save()
        except OSError as exc:  # pragma: no cover - disk problems
            LOGGER.warning("cannot save session: %s", exc)


def _describe(call: llm.ToolCall) -> str:
    if not call.arguments:
        return call.name
    try:
        return f"{call.name} {json.dumps(call.arguments, ensure_ascii=False)[:120]}"
    except (TypeError, ValueError):
        return call.name


def _unique_sources(sources: list[Source]) -> list[Source]:
    seen: set[str] = set()
    unique: list[Source] = []
    for source in sources:
        if source.url and source.url not in seen:
            seen.add(source.url)
            unique.append(source)
    return unique[:6]
