import json

import httpx
import pytest

from chinchilla.core import llm
from chinchilla.store import config


def openai_sse(*events: dict) -> bytes:
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return (body + "data: [DONE]\n\n").encode()


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_streams_text_and_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["model"] == "test-model"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=openai_sse(
                {"choices": [{"delta": {"content": "Hola"}}]},
                {"choices": [{"delta": {"content": " mundo"}}]},
                {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}},
            ),
        )

    provider = llm.OpenAICompatible("custom", "https://api.test/v1", "sk-x", "test-model", client=make_client(handler))
    chunks = list(provider.chat([llm.Message("user", "hi", images=[b"jpeg-bytes"])]))
    assert "".join(chunk.text for chunk in chunks if chunk.type == "text") == "Hola mundo"
    assert chunks[-1].type == "done"
    assert provider.last_usage["prompt_tokens"] == 12


def test_openai_request_contains_image_and_tools():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=openai_sse())

    provider = llm.OpenAICompatible("openai", "https://api.test/v1", "sk-x", "test-model", client=make_client(handler))
    tools = [llm.ToolSpec("search", "search the web", {"type": "object", "properties": {}})]
    list(provider.chat([llm.Message("user", "what is this", images=[b"abc"])], tools=tools))

    content = captured["body"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "what is this"}
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert captured["body"]["tools"][0]["function"]["name"] == "search"


def test_openai_assembles_streamed_tool_calls():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=openai_sse(
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "search", "arguments": "{\"que"}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "ry\": \"weather\"}"}}]}}]},
            ),
        )

    provider = llm.OpenAICompatible("custom", "https://api.test/v1", "sk-x", "m", client=make_client(handler))
    calls = [chunk.tool_call for chunk in provider.chat([llm.Message("user", "x")]) if chunk.type == "tool_call"]
    assert calls[0].name == "search"
    assert calls[0].arguments == {"query": "weather"}
    assert calls[0].id == "call_1"


def test_openai_reports_http_errors():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    provider = llm.OpenAICompatible("openai", "https://api.test/v1", "sk-x", "m", client=make_client(handler))
    with pytest.raises(llm.ProviderError) as error:
        list(provider.chat([llm.Message("user", "x")]))
    assert "401" in str(error.value) and "bad key" in str(error.value)


def test_anthropic_streams_text_and_tool_use():
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hallo"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "search", "input": {}}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"query\": \"news\"}"}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"input_tokens": 30, "output_tokens": 8}},
    ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["system"] == "be nice"
        assert payload["messages"][0]["content"][0]["type"] == "image"
        assert payload["tools"][0]["input_schema"] == {"type": "object"}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    provider = llm.Anthropic("anthropic", "https://api.test", "sk-ant", "claude-test", client=make_client(handler))
    chunks = list(
        provider.chat(
            [
                llm.Message("system", "be nice"),
                llm.Message("user", "what is this", images=[b"abc"]),
            ],
            tools=[llm.ToolSpec("search", "search the web", {"type": "object"})],
        )
    )
    assert "".join(chunk.text for chunk in chunks if chunk.type == "text") == "Hallo"
    tool_calls = [chunk.tool_call for chunk in chunks if chunk.type == "tool_call"]
    assert tool_calls[0].arguments == {"query": "news"}
    assert provider.last_usage["input_tokens"] == 30


def test_provider_requires_configuration():
    with pytest.raises(llm.ProviderError):
        llm.OpenAICompatible("openai", "https://api.test/v1", "", "m")
    with pytest.raises(llm.ProviderError):
        llm.Anthropic("anthropic", "https://api.test", "sk", "")


def test_build_provider_uses_settings_and_env(xdg, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    settings = config.default_settings()
    settings.active_provider = "openai"
    settings.providers["openai"].model = "gpt-test"
    provider = llm.build_provider(settings)
    assert isinstance(provider, llm.OpenAICompatible)
    assert provider.api_key == "sk-env"
    assert provider.model == "gpt-test"

    settings.active_provider = "anthropic"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    assert isinstance(llm.build_provider(settings), llm.Anthropic)


def test_anthropic_stream_keeps_input_usage_from_message_start():
    events = [
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 40,
                    "cache_read_input_tokens": 900,
                    "cache_creation_input_tokens": 20,
                    "output_tokens": 1,
                }
            },
        },
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 25}},
    ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    provider = llm.Anthropic("anthropic", "https://api.test", "sk-ant", "claude-test", client=make_client(handler))
    list(provider.chat([llm.Message("user", "hi")]))

    assert provider.last_usage["input_tokens"] == 40
    assert provider.last_usage["cache_read_input_tokens"] == 900
    assert provider.last_usage["output_tokens"] == 25, "message_delta carries the final count"


def test_anthropic_usage_becomes_cached_input_tokens():
    from chinchilla.core.thread import Usage

    usage = Usage.from_payload(
        {"input_tokens": 40, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 20, "output_tokens": 25}
    )

    assert (usage.input_tokens, usage.cached_tokens) == (960, 900)


def test_streamed_error_body_is_read_despite_not_being_read_yet():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited, retry in 3s"}})

    provider = llm.OpenAICompatible("custom", "https://api.test/v1", "sk-x", "m", client=make_client(handler))

    with pytest.raises(llm.ProviderError) as error:
        list(provider.chat([llm.Message("user", "hi")]))

    assert "429" in str(error.value) and "rate limited" in str(error.value)


def test_anthropic_stream_error_is_reported_instead_of_an_empty_answer():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"type": "error", "error": {"message": "max_tokens too large"}})

    provider = llm.Anthropic("anthropic", "https://api.test", "sk-ant", "claude-test", client=make_client(handler))

    with pytest.raises(llm.ProviderError) as error:
        list(provider.chat([llm.Message("user", "hi")]))

    assert "max_tokens too large" in str(error.value)


def test_base_url_without_a_scheme_gets_one():
    provider = llm.OpenAICompatible("custom", "127.0.0.1:8000/v1/", "", "local")

    assert provider.base_url == "http://127.0.0.1:8000/v1"


def test_a_local_endpoint_needs_no_api_key():
    provider = llm.OpenAICompatible("custom", "http://localhost:8080/v1", "", "local")

    assert "Authorization" not in provider._headers()


def test_reasoning_effort_is_sent_in_the_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=openai_sse())

    provider = llm.OpenAICompatible(
        "custom", "https://api.test/v1", "sk-x", "test-model", client=make_client(handler), reasoning_effort="High"
    )
    list(provider.chat([llm.Message("user", "hi")]))

    assert captured["body"]["reasoning_effort"] == "high"


def test_no_reasoning_effort_field_when_unset():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=openai_sse())

    provider = llm.OpenAICompatible("custom", "https://api.test/v1", "sk-x", "test-model", client=make_client(handler))
    list(provider.chat([llm.Message("user", "hi")]))

    assert "reasoning_effort" not in captured["body"]


def test_a_server_that_refuses_reasoning_effort_still_answers():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "reasoning_effort" in body:
            return httpx.Response(
                400,
                json={"error": {"message": "unrecognized field reasoning_effort"}},
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=openai_sse({"choices": [{"delta": {"content": "ok"}}]}),
        )

    provider = llm.OpenAICompatible(
        "custom", "https://api.test/v1", "sk-x", "test-model", client=make_client(handler), reasoning_effort="medium"
    )
    chunks = list(provider.chat([llm.Message("user", "hi")]))

    assert "".join(chunk.text for chunk in chunks if chunk.type == "text") == "ok"
    assert "reasoning_effort" in bodies[0]
    assert "reasoning_effort" not in bodies[1]
    assert provider._drop_reasoning is True


def test_an_unrelated_error_keeps_the_reasoning_effort():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "max_tokens too large"}})

    provider = llm.OpenAICompatible(
        "custom", "https://api.test/v1", "sk-x", "test-model", client=make_client(handler), reasoning_effort="low"
    )
    with pytest.raises(llm.ProviderError):
        list(provider.chat([llm.Message("user", "hi")]))

    assert len(calls) == 1
