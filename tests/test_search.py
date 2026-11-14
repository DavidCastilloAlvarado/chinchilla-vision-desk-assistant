import sys
from pathlib import Path

import pytest

from chinchilla.core import search
from chinchilla.store import config

FAKE_SERVER = Path(__file__).with_name("fake_mcp_server.py")


def fake_settings() -> config.Settings:
    settings = config.default_settings()
    settings.mcp_command = [sys.executable, str(FAKE_SERVER)]
    return settings


def test_client_lists_tools_and_calls_them():
    client = search.MCPClient([sys.executable, str(FAKE_SERVER)], timeout=10)
    with client:
        names = [tool["name"] for tool in client.list_tools()]
        assert names == ["search", "fetch"]
        result = client.call_tool("search", {"query": "token expiry"})
    text = result["content"][0]["text"]
    assert 'search({"query": "token expiry"})' in text


def test_web_search_exposes_tool_specs():
    web = search.WebSearch(fake_settings())
    assert web.start()
    try:
        tools = web.tools()
        assert {tool.name for tool in tools} == {"search", "fetch"}
        assert tools[0].parameters["type"] == "object"
    finally:
        web.close()


def test_web_search_extracts_sources():
    web = search.WebSearch(fake_settings())
    assert web.start()
    try:
        result = web.call("search", {"query": "x"})
    finally:
        web.close()
    assert result.ok
    urls = [source.url for source in result.sources]
    assert urls == ["https://example.com/tokens", "https://example.org/retries"]
    assert result.sources[0].title == "Token expiry explained"


def test_missing_server_is_reported_not_raised():
    settings = config.default_settings()
    settings.mcp_command = ["definitely-not-a-real-binary", "mcp"]
    web = search.WebSearch(settings)
    assert web.start() is False
    assert "not installed" in (web.error or "")


def test_disabled_search_counts_as_unavailable():
    settings = config.default_settings()
    settings.mcp_enabled = False
    ok, detail = search.probe_server(settings)
    assert ok is False and "disabled" in detail


def test_sources_limit_and_dedupe():
    text = "[a](https://a.test) [a again](https://a.test) https://b.test"
    sources = search.extract_sources(text)
    assert [source.url for source in sources] == ["https://a.test", "https://b.test"]


def test_citations_are_scrubbed_when_out_of_range():
    sources = [search.Source(title="one", url="https://a.test")]
    assert search.scrub_citations("see [1] and [2] and [0]", sources) == "see [1] and  and "


def test_budget_stops_after_the_limit():
    budget = search.Budget(max_calls=2, seconds=5)
    assert budget.take() and budget.take()
    assert not budget.take()


def test_unknown_method_raises():
    client = search.MCPClient([sys.executable, str(FAKE_SERVER)], timeout=10)
    with client:
        with pytest.raises(search.MCPError):
            client._request("tools/nope", {})


def test_resolved_mcp_prefers_the_configured_command(xdg):
    settings = config.default_settings()
    settings.mcp_command = [sys.executable, str(FAKE_SERVER)]

    command, env = config.resolved_mcp(settings)

    assert command == [sys.executable, str(FAKE_SERVER)]
    assert env["CHROME_PATH"]


def test_resolved_mcp_reads_the_environment(xdg, monkeypatch, tmp_path):
    npx = tmp_path / "npx"
    npx.write_text("#!/bin/sh\n", encoding="utf-8")
    npx.chmod(0o755)
    monkeypatch.setenv("WEBSEARCH_MCP_COMMAND", str(npx))
    monkeypatch.setenv("WEBSEARCH_MCP_ARGS", "-y custom-server mcp")
    monkeypatch.setenv("GSEARCH_PROFILE", "/tmp/profile")

    command, env = config.resolved_mcp(config.default_settings())

    assert command == [str(npx), "-y", "custom-server", "mcp"]
    assert env["GSEARCH_PROFILE"] == "/tmp/profile"
    assert env["PATH"].split(":")[0] == str(tmp_path)


def test_find_node_bin_skips_a_missing_binary(xdg, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")

    assert config.find_node_bin("definitely-not-installed") is None
