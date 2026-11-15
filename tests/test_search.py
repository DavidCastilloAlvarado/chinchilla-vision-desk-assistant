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


DSH_OUTPUT = """Google search results for: S&P 500 50-day moving average
(source: https://www.google.com/search?q=S%26P+500+50-day&hl=en&gl=us&num=15&ie=UTF-8)

Organic results:
1. S&P 500 Index Technical Analysis
   https://www.barchart.com/stocks/quotes/%24SPX/technical-analysis
   500 Index with Moving Average, 50-Day 7,667.46 -186.04 -2.40%
2. S&P 500 Index Advanced Charts - SPX
   https://www.marketwatch.com/investing/index/spx/charts
   S&P 500 Index advanced index charts by MarketWatch.
:root{--COEmY:var(--YLNNHc);--xhUGwc:#22242a} https://www.w3.org/2000/svg
"""


def test_real_result_blocks_become_titled_sources():
    sources = search.extract_sources(DSH_OUTPUT)

    assert [(s.title, s.url) for s in sources] == [
        (
            "S&P 500 Index Technical Analysis",
            "https://www.barchart.com/stocks/quotes/%24SPX/technical-analysis",
        ),
        (
            "S&P 500 Index Advanced Charts - SPX",
            "https://www.marketwatch.com/investing/index/spx/charts",
        ),
    ]


def test_search_pages_and_assets_are_never_listed_as_sources():
    text = (
        "1. Some page\n   https://example.com/page\n"
        "(source: https://www.google.com/search?q=hello)\n"
        "https://www.w3.org/2000/svg\n"
        "https://example.org/styles.css\n"
    )
    sources = search.extract_sources(text)

    assert [source.url for source in sources] == ["https://example.com/page"]
    assert all(s.title != "(source:" for s in sources)


def test_a_url_without_a_title_falls_back_to_its_host():
    sources = search.extract_sources("https://finance.yahoo.com/quote/%5EGSPC/history/")
    assert sources[0].title == "finance.yahoo.com"


def test_more_results_are_kept_than_the_old_six_cap():
    text = "\n".join(
        f"{index}. result {index}\n   https://example.com/{index}" for index in range(1, 10)
    )
    assert len(search.extract_sources(text)) == 9


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


def test_probe_server_handshake_reports_the_tools():
    ok, detail = search.probe_server(fake_settings(), handshake=True)

    assert ok is True
    assert "tools: search, fetch" in detail


def test_probe_server_handshake_reports_a_dead_server():
    settings = config.default_settings()
    settings.mcp_command = [sys.executable, "-c", "import sys; sys.exit(3)"]

    ok, detail = search.probe_server(settings, handshake=True)

    assert ok is False
    assert detail
