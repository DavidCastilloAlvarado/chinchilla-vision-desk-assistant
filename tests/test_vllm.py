"""Speak the contract a local vLLM server implements.

vLLM serves the OpenAI chat completions API, so these tests run the real
adapters against a small server that copies the parts we depend on: SSE
streaming, ``stream_options.include_usage``, ``image_url`` data URIs, prefix
cache counters and the two errors a local deployment produces.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from PIL import Image

from chinchilla.core import agent as agent_module
from chinchilla.core import capture as capture_module
from chinchilla.core import llm
from chinchilla.core.thread import Turn
from chinchilla.store import config, session as session_store


class FakeVLLM:
    """Minimal stand-in for `vllm serve`, including its refusal to do tools."""

    def __init__(self, max_model_len: int = 4096, tool_parser: bool = False):
        self.max_model_len = max_model_len
        self.tool_parser = tool_parser
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.seen_prompts: set[str] = set()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> "FakeVLLM":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    # ------------------------------------------------------------- behaviour

    def _prompt_tokens(self, payload: dict) -> int:
        chars = 0
        for message in payload.get("messages") or []:
            content = message.get("content")
            if isinstance(content, str):
                chars += len(content)
            for part in content if isinstance(content, list) else []:
                if part.get("type") == "text":
                    chars += len(part.get("text", ""))
                elif part.get("type") == "image_url":
                    chars += 2800  # a cut, roughly the tokens vLLM charges us
        return max(1, chars // 4)

    def _reply(self, handler: BaseHTTPRequestHandler, payload: dict) -> None:
        prompt_tokens = self._prompt_tokens(payload)
        if prompt_tokens > self.max_model_len:
            self._error(
                handler,
                f"This model's maximum context length is {self.max_model_len} tokens. "
                f"However, you requested {prompt_tokens} tokens.",
            )
            return
        if payload.get("tools") and payload.get("tool_choice") == "auto" and not self.tool_parser:
            self._error(handler, '"auto" tool choice requires --enable-auto-tool-choice and '
                                 "--tool-call-parser to be set")
            return

        key = json.dumps(payload.get("messages"))[:-40]
        cached = min(1024, prompt_tokens) if key in self.seen_prompts else 0
        self.seen_prompts.add(key)
        events = [
            {"choices": [{"delta": {"content": "Recibido"}}]},
            {"choices": [{"delta": {"content": "."}}]},
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": 2,
                    "total_tokens": prompt_tokens + 2,
                    "prompt_tokens_details": {"cached_tokens": cached},
                },
            },
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        handler.send_response(200)
        handler.send_header("content-type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(body.encode())

    def _error(self, handler: BaseHTTPRequestHandler, message: str) -> None:
        body = json.dumps({"object": "error", "message": message, "code": 400}).encode()
        handler.send_response(400)
        handler.send_header("content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(body)

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server naming
                length = int(self.headers.get("content-length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                server.requests.append(payload)
                server.headers.append(dict(self.headers))
                server._reply(self, payload)

            def log_message(self, *_args) -> None:
                pass

        return Handler


def _settings(base_url: str, **overrides) -> config.Settings:
    settings = config.default_settings()
    settings.active_provider = "custom"
    settings.providers["custom"].base_url = base_url
    settings.providers["custom"].model = "local-vl"
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def test_local_server_needs_no_api_key_and_receives_no_auth_header():
    with FakeVLLM() as server:
        provider = llm.OpenAICompatible("custom", server.base_url, "", "local-vl")
        chunks = list(provider.chat([llm.Message("user", "hola")], stream=True))

    assert "".join(chunk.text for chunk in chunks if chunk.type == "text") == "Recibido."
    assert "authorization" not in {key.lower() for key in server.headers[0]}
    assert server.requests[0]["stream_options"] == {"include_usage": True}


def test_a_cut_reaches_the_server_as_a_data_uri_and_usage_is_counted():
    with FakeVLLM() as server:
        settings = _settings(server.base_url)
        session = session_store.Session(title="Local")
        capture = session.add_capture(Image.new("RGB", (80, 50), (30, 60, 90)))
        provider = llm.OpenAICompatible("custom", server.base_url, "", "local-vl")
        agent = agent_module.Agent(session, settings, provider=provider)

        list(agent.run(Turn(role="user", text="What is this?", captures=[capture.id])))

        user = [m for m in server.requests[0]["messages"] if m["role"] == "user"][-1]
        parts = user["content"]
        assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        usage = session.turns[-1].usage
        assert usage is not None and usage.input_tokens > 0
        assert session.turns[-1].text == "Recibido."


def test_prefix_cache_counters_are_read_back():
    with FakeVLLM() as server:
        provider = llm.OpenAICompatible("custom", server.base_url, "", "local-vl")
        messages = [llm.Message("user", "x" * 5000)]
        list(provider.chat(messages, stream=True))
        first = dict(provider.last_usage)
        list(provider.chat(messages, stream=True))
        second = dict(provider.last_usage)

    assert first["prompt_tokens_details"]["cached_tokens"] == 0
    assert second["prompt_tokens_details"]["cached_tokens"] > 0


def test_tools_without_a_tool_parser_surface_the_vllm_error():
    with FakeVLLM() as server:
        provider = llm.OpenAICompatible("custom", server.base_url, "", "local-vl")
        tools = [llm.ToolSpec("search", "search", {"type": "object", "properties": {}})]

        with pytest.raises(llm.ProviderError) as error:
            list(provider.chat([llm.Message("user", "hi")], tools=tools))

    assert "tool-call-parser" in str(error.value)


def test_the_same_call_passes_with_the_tool_parser_enabled():
    with FakeVLLM(tool_parser=True) as server:
        provider = llm.OpenAICompatible("custom", server.base_url, "", "local-vl")
        tools = [llm.ToolSpec("search", "search", {"type": "object", "properties": {}})]

        chunks = list(provider.chat([llm.Message("user", "hi")], tools=tools))

    assert any(chunk.type == "text" for chunk in chunks)
    assert server.requests[0]["tool_choice"] == "auto"


def test_context_overflow_reaches_the_user_as_a_readable_error():
    with FakeVLLM(max_model_len=1000) as server:
        provider = llm.OpenAICompatible("custom", server.base_url, "", "local-vl")
        with pytest.raises(llm.ProviderError) as error:
            list(provider.chat([llm.Message("user", "y" * 8000)]))

    assert "maximum context length" in str(error.value)


def test_exported_base_url_and_model_beat_the_env_file(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")

    provider = config.provider_from_env("custom")

    assert provider.base_url == "http://127.0.0.1:8000/v1"
    assert provider.model == "Qwen/Qwen2.5-VL-7B-Instruct"


def test_local_endpoint_detection():
    assert config.is_local_endpoint("http://localhost:8000/v1")
    assert config.is_local_endpoint("http://127.0.0.1:8000/v1")
    assert config.is_local_endpoint("http://host.docker.internal:8000/v1")
    assert not config.is_local_endpoint("https://api.openai.com/v1")
    assert not config.is_local_endpoint("")