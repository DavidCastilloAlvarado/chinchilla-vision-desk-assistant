"""Provider adapters.

OpenAI, OpenRouter and the custom endpoint share one client, Anthropic has its
own. Both expose the same streaming interface: chat() yields Chunk objects for
text, tool calls and usage.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

import httpx

from .. import log
from ..store import config

LOGGER = log.get("llm")
DEFAULT_TIMEOUT = 120.0
ANTHROPIC_VERSION = "2023-06-01"
# optional payload fields, and the attribute that stops sending each one
_FIELD_FLAGS = {
    "reasoning_effort": "_drop_reasoning",
    "max_tokens": "_drop_max_tokens",
    "temperature": "_drop_temperature",
}


class ProviderError(RuntimeError):
    """A provider could not be reached or refused the request."""


@dataclass
class Message:
    role: str
    text: str = ""
    images: list[bytes] = field(default_factory=list)
    tool_call_id: str = ""
    tool_name: str = ""
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def as_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }


@dataclass
class Chunk:
    type: str  # text | reasoning | tool_call | usage | done
    text: str = ""
    tool_call: ToolCall | None = None
    usage: dict[str, int] = field(default_factory=dict)


def _reasoning_text(payload: dict[str, Any]) -> str:
    """The thinking stream, under the names servers actually use.

    vLLM, llama.cpp and LM Studio send `reasoning_content`; OpenRouter and some
    gateways send `reasoning`. Anything else is ignored, so an unknown field can
    never leak into the answer.
    """
    for key in ("reasoning_content", "reasoning"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def max_tokens_from_error(exc: ProviderError) -> int | None:
    """`max_tokens: 32768 > 4096, which is the maximum allowed` -> 4096."""
    message = str(exc)
    patterns = (
        r"max_tokens:\s*\d+\s*>\s*(\d+)",
        r"maximum allowed[^0-9]*(\d+)",
        r"(\d+)\s*output tokens",
    )
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            value = int(match.group(1))
            if 256 <= value <= 1_000_000:
                return value
    return None


def _image_media_type(image: bytes) -> str:
    """The real format, so a server that validates it does not refuse the turn."""
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _data_uri(image: bytes) -> str:
    media = _image_media_type(image)
    return f"data:{media};base64," + base64.b64encode(image).decode("ascii")


def _sse_events(lines: Iterable[str]) -> Iterator[dict]:
    """Parse server sent events into JSON payloads."""
    for line in lines:
        if not line:
            continue
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in ("", "[DONE]"):
            if payload == "[DONE]":
                return
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def normalise_base_url(url: str) -> str:
    """`192.168.1.5:1234/v1` is a common paste; httpx needs a scheme."""
    cleaned = (url or "").strip().rstrip("/")
    if cleaned and "://" not in cleaned:
        cleaned = "http://" + cleaned
    return cleaned


def raise_for_status(provider_id: str, response: httpx.Response) -> None:
    """Turn an error response into a ProviderError, streaming or not.

    A streamed response has no body until it is read, so `response.text` raises
    `ResponseNotRead`; that used to escape as an unhandled exception and hide
    the server's own message (rate limits, context overflow, a vLLM 400).
    """
    if response.status_code < 400:
        return
    detail = ""
    try:
        raw = response.read() or b""
    except Exception:
        raw = b""
    try:
        body = json.loads(raw or b"{}")
    except Exception:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or ""
        if not detail:
            detail = body.get("message") or ""
    if not detail:
        detail = raw.decode("utf-8", "replace")[:200]
    raise ProviderError(f"{provider_id}: HTTP {response.status_code} {detail}".strip())


class OpenAICompatible:
    def __init__(
        self,
        provider_id: str,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
        temperature: float = 0.2,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        reasoning_effort: str = "",
    ) -> None:
        base_url = normalise_base_url(base_url)
        if not base_url:
            raise ProviderError(f"{provider_id}: no base url configured")
        if not api_key and not config.is_local_endpoint(base_url):
            raise ProviderError(f"{provider_id}: no api key configured")
        if not model:
            raise ProviderError(f"{provider_id}: no model configured")
        self.id = provider_id
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = (reasoning_effort or "").strip().lower()
        self.last_finish_reason = ""
        self._drop_reasoning = False
        self._drop_max_tokens = False
        self._drop_temperature = False
        self._client = client
        self.last_usage: dict[str, int] = {}

    # ------------------------------------------------------------- requests

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.id == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/chinchilla"
            headers["X-Title"] = "Chinchilla"
        return headers

    def _payload(
        self, messages: list[Message], tools: list[ToolSpec] | None, stream: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message(item) for item in messages],
            "stream": stream,
        }
        if self.temperature is not None and not self._drop_temperature:
            payload["temperature"] = self.temperature
        if self.max_tokens and not self._drop_max_tokens:
            payload["max_tokens"] = self.max_tokens
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if self.reasoning_effort and not self._drop_reasoning:
            payload["reasoning_effort"] = self.reasoning_effort
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"
        return payload

    def _message(self, message: Message) -> dict[str, Any]:
        if message.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.text,
            }
        if message.role == "assistant" and message.tool_calls:
            return {
                "role": "assistant",
                "content": message.text or None,
                "tool_calls": message.tool_calls,
            }
        if not message.images:
            return {"role": message.role, "content": message.text}
        content: list[dict[str, Any]] = [{"type": "text", "text": message.text}]
        for image in message.images:
            content.append({"type": "image_url", "image_url": {"url": _data_uri(image)}})
        return {"role": message.role, "content": content}

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        client = self._client or httpx
        url = f"{self.base_url}/chat/completions"
        try:
            if self._client is not None:
                return self._client.post(url, json=payload, headers=self._headers())
            return httpx.post(
                url, json=payload, headers=self._headers(), timeout=DEFAULT_TIMEOUT
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.id}: {exc}") from exc

    # --------------------------------------------------------------- stream

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> Iterator[Chunk]:
        """Stream one completion, dropping optional fields the server refuses."""
        while True:
            emitted = False
            try:
                for chunk in self._chat_payload(messages, tools, stream):
                    emitted = True
                    yield chunk
                return
            except ProviderError as exc:
                field = None if emitted else self._refused_field(exc)
                if field is None:
                    raise
                if self._narrow_optional(field, exc):
                    LOGGER.warning("%s: retrying with a narrower %s (%s)", self.id, field, exc)
                    continue
                LOGGER.warning("%s: retrying without %s (%s)", self.id, field, exc)
                setattr(self, _FIELD_FLAGS[field], True)

    def _narrow_optional(self, field: str, exc: ProviderError) -> bool:
        """Replace a refused optional value with one the server accepts."""
        return False

    def _refused_field(self, exc: ProviderError) -> str | None:
        """Optional payload fields this server dislikes, so we can retry without them."""
        message = str(exc).lower()
        if (
            self.reasoning_effort
            and not self._drop_reasoning
            and ("reasoning_effort" in message or "reasoning effort" in message)
        ):
            return "reasoning_effort"
        if self.max_tokens and not self._drop_max_tokens and "max_tokens" in message:
            return "max_tokens"
        if (
            self.temperature is not None
            and not self._drop_temperature
            and "temperature" in message
        ):
            return "temperature"
        return None

    def _chat_payload(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        stream: bool,
    ) -> Iterator[Chunk]:
        payload = self._payload(messages, tools, stream)
        if not stream:
            response = self._post(payload)
            self._raise_for_status(response)
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            self.last_finish_reason = choice.get("finish_reason") or ""
            message = choice.get("message") or {}
            reasoning = _reasoning_text(message)
            if reasoning:
                yield Chunk("reasoning", text=reasoning)
            if message.get("content"):
                yield Chunk("text", text=message["content"])
            for call in message.get("tool_calls") or []:
                yield Chunk("tool_call", tool_call=self._tool_call(call))
            self.last_usage = data.get("usage") or {}
            yield Chunk("usage", usage=self.last_usage)
            yield Chunk("done")
            return

        calls: dict[int, dict[str, Any]] = {}
        with self._stream(payload) as response:
            self._raise_for_status(response)
            for event in _sse_events(response.iter_lines()):
                if event.get("usage"):
                    self.last_usage = event["usage"]
                choices = event.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    self.last_finish_reason = choice["finish_reason"]
                delta = choice.get("delta") or {}
                reasoning = _reasoning_text(delta)
                if reasoning:
                    yield Chunk("reasoning", text=reasoning)
                if delta.get("content"):
                    yield Chunk("text", text=delta["content"])
                for call in delta.get("tool_calls") or []:
                    index = int(call.get("index", 0))
                    slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if call.get("id"):
                        slot["id"] = call["id"]
                    function = call.get("function") or {}
                    if function.get("name"):
                        slot["name"] = function["name"]
                    if function.get("arguments"):
                        slot["arguments"] += function["arguments"]
        for index in sorted(calls):
            yield Chunk("tool_call", tool_call=self._tool_call({"function": calls[index], "id": calls[index]["id"]}))
        if self.last_usage:
            yield Chunk("usage", usage=self.last_usage)
        yield Chunk("done")

    def _stream(self, payload: dict[str, Any]):
        url = f"{self.base_url}/chat/completions"
        headers = self._headers()
        if self._client is not None:
            return _StreamContext(self._client.stream("POST", url, json=payload, headers=headers))
        return _StreamContext(
            httpx.stream("POST", url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
        )

    def _tool_call(self, call: dict[str, Any]) -> ToolCall:
        function = call.get("function") or {}
        raw = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            arguments = {}
        return ToolCall(
            id=call.get("id") or f"call_{function.get('name', 'tool')}",
            name=function.get("name", ""),
            arguments=arguments,
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        raise_for_status(self.id, response)


class _StreamContext:
    """Small wrapper so tests can pass any context manager."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, *args):
        return self._inner.__exit__(*args)


class Anthropic:
    def __init__(
        self,
        provider_id: str = "anthropic",
        base_url: str = "https://api.anthropic.com",
        api_key: str = "",
        model: str = "",
        client: httpx.Client | None = None,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
        temperature: float = 0.2,
    ) -> None:
        base_url = normalise_base_url(base_url)
        if not api_key:
            raise ProviderError("anthropic: no api key configured")
        if not model:
            raise ProviderError("anthropic: no model configured")
        self.id = provider_id
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = client
        self.last_usage: dict[str, int] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _track_usage(self, usage: dict) -> None:
        """Merge a usage block: message_start sends input, message_delta the final output."""
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                self.last_usage[key] = int(value)

    def _payload(
        self, messages: list[Message], tools: list[ToolSpec] | None, stream: bool
    ) -> dict[str, Any]:
        system_parts = [item.text for item in messages if item.role == "system"]
        chat_messages = []
        for message in messages:
            if message.role == "system":
                continue
            if message.role == "tool":
                chat_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.text,
                            }
                        ],
                    }
                )
                continue
            if message.role == "assistant":
                blocks: list[dict[str, Any]] = []
                if message.text:
                    blocks.append({"type": "text", "text": message.text})
                for call in message.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call["id"],
                            "name": call["function"]["name"],
                            "input": json.loads(call["function"]["arguments"] or "{}"),
                        }
                    )
                chat_messages.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
                continue
            blocks = []
            for image in message.images:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _image_media_type(image),
                            "data": base64.b64encode(image).decode("ascii"),
                        },
                    }
                )
            blocks.append({"type": "text", "text": message.text})
            chat_messages.append({"role": "user", "content": blocks})

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": chat_messages,
            "stream": stream,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in tools
            ]
        return payload

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> Iterator[Chunk]:
        """Stream one reply, lowering `max_tokens` if the model allows less."""
        try:
            yield from self._chat(messages, tools, stream)
        except ProviderError as exc:
            limit = max_tokens_from_error(exc)
            if limit is None or limit >= self.max_tokens:
                raise
            LOGGER.warning("anthropic: max_tokens %s refused, retrying with %s", self.max_tokens, limit)
            self.max_tokens = limit
            yield from self._chat(messages, tools, stream)

    def _chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        stream: bool = True,
    ) -> Iterator[Chunk]:
        payload = self._payload(messages, tools, stream)
        url = f"{self.base_url}/v1/messages"
        if not stream:
            response = self._post(url, payload, stream=False)
            raise_for_status(self.id, response)
            data = response.json()
            for block in data.get("content") or []:
                if block.get("type") == "thinking" and block.get("thinking"):
                    yield Chunk("reasoning", text=block["thinking"])
                elif block.get("type") == "text":
                    yield Chunk("text", text=block.get("text", ""))
                elif block.get("type") == "tool_use":
                    yield Chunk(
                        "tool_call",
                        tool_call=ToolCall(id=block.get("id", ""), name=block.get("name", ""), arguments=block.get("input") or {}),
                    )
            self.last_usage = data.get("usage") or {}
            yield Chunk("usage", usage=self.last_usage)
            yield Chunk("done")
            return

        pending: dict[str, dict[str, Any]] = {}
        with self._post(url, payload, stream=True) as response:
            raise_for_status(self.id, response)
            for event in _sse_events(response.iter_lines()):
                kind = event.get("type")
                if kind == "content_block_start":
                    block = event.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        pending[block.get("id", "")] = {
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "json": "",
                        }
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "thinking_delta" and delta.get("thinking"):
                        yield Chunk("reasoning", text=delta["thinking"])
                    elif delta.get("type") == "text_delta" and delta.get("text"):
                        yield Chunk("text", text=delta["text"])
                    elif delta.get("type") == "input_json_delta":
                        for slot in pending.values():
                            slot["json"] += delta.get("partial_json", "")
                            break
                elif kind == "message_start":
                    self._track_usage(((event.get("message") or {}).get("usage")) or {})
                elif kind == "message_delta":
                    self._track_usage(event.get("usage") or {})
                elif kind == "error":
                    raise ProviderError(f"anthropic: {(event.get('error') or {}).get('message', 'stream error')}")
        for slot in pending.values():
            try:
                arguments = json.loads(slot["json"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            yield Chunk("tool_call", tool_call=ToolCall(id=slot["id"], name=slot["name"], arguments=arguments))
        if self.last_usage:
            yield Chunk("usage", usage=self.last_usage)
        yield Chunk("done")

    def _post(self, url: str, payload: dict[str, Any], stream: bool):
        headers = self._headers()
        try:
            if self._client is not None:
                return _StreamContext(self._client.stream("POST", url, json=payload, headers=headers)) if stream else self._client.post(url, json=payload, headers=headers)
            return _StreamContext(httpx.stream("POST", url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT, follow_redirects=True)) if stream else httpx.post(url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
        except httpx.HTTPError as exc:
            raise ProviderError(f"anthropic: {exc}") from exc


def build_provider(settings: config.Settings, client: httpx.Client | None = None):
    """Create the adapter for the active provider."""
    provider = config.resolved_provider(settings)
    key = config.resolve_key(provider.id) or ""
    if provider.kind == "copilot":
        from . import copilot as copilot_module

        return copilot_module.CopilotProvider(
            model=provider.model,
            client=client,
            max_tokens=settings.max_tokens,
            reasoning_effort=settings.reasoning_effort,
        )
    if provider.kind == "anthropic":
        return Anthropic(
            provider_id=provider.id,
            base_url=provider.base_url or "https://api.anthropic.com",
            api_key=key,
            model=provider.model,
            client=client,
            max_tokens=settings.max_tokens,
        )
    return OpenAICompatible(
        provider_id=provider.id,
        base_url=provider.base_url,
        api_key=key,
        model=provider.model,
        client=client,
        max_tokens=settings.max_tokens,
        reasoning_effort=settings.reasoning_effort,
    )
