"""Web search through an MCP stdio server.

The agent gets real tools (search, fetch, search_and_fetch) from the server
described in settings.mcp_command, and every URL the server returns becomes a
citation. Budgets keep a single turn from turning into a crawl.
"""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .. import log
from ..store import config
from .llm import ToolSpec
from .thread import Source

LOGGER = log.get("search")
PROTOCOL_VERSION = "2024-11-05"
# A browsing turn is allowed to take a while: dropping the answer because the
# second search needed ten more seconds is worse than waiting.
MAX_TOOL_CALLS = 6
TOOL_DEADLINE = 150.0
CALL_TIMEOUT = 60.0
SOURCE_LIMIT = 10

_MD_LINK = re.compile(r"\[([^\]]{1,160})\]\((https?://[^)\s]+)\)")
_URL = re.compile(r"https?://[^\s<>\)\]\"']+")
_LIST_ITEM = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*+])\s+(?P<body>\S.*?)\s*$")
_BARE_URL = re.compile(r"^<?(?P<url>https?://[^\s<>]+?)>?\s*$")
_MARKUP = re.compile(r"</?(?:b|i|em|strong|span|code|tt|small|big|a|p|br|div)\b[^>]*>", re.I)

# Result pages and asset hosts show up in scraped text but are not sources.
_NOT_A_SOURCE_HOSTS = {
    "google.com",
    "www.google.com",
    "news.google.com",
    "lens.google.com",
    "www.bing.com",
    "bing.com",
    "duckduckgo.com",
    "html.duckduckgo.com",
    "search.yahoo.com",
    "schema.org",
    "fonts.googleapis.com",
}
_NOT_A_SOURCE_PATHS = (
    "/2000/svg",
    "/1999/xlink",
    "/2000/xmlns",
    "/xml/1998/namespace",
)
_ASSET_SUFFIXES = (
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
)


class MCPError(RuntimeError):
    pass


class MCPClient:
    """Minimal JSON-RPC client for an MCP server over stdio."""

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        timeout: float = CALL_TIMEOUT,
    ) -> None:
        self.command = list(command)
        self.env = dict(env or {})
        self.timeout = timeout
        self._process: subprocess.Popen | None = None
        self._next_id = 0
        self._stderr_tail: list[str] = []

    # ---------------------------------------------------------------- process

    def start(self) -> None:
        if self._process is not None:
            return
        environment = os.environ.copy()
        environment.update({key: str(value) for key, value in self.env.items()})
        environment.setdefault("NODE_NO_WARNINGS", "1")
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise MCPError(f"cannot start {self.command[0]}: {exc}") from exc
        self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "chinchilla", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    def __enter__(self) -> "MCPClient":
        self.start()
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    # ---------------------------------------------------------------- framing

    def _write(self, payload: dict) -> None:
        if self._process is None or self._process.stdin is None:
            raise MCPError("server is not running")
        self._process.stdin.write(json.dumps(payload) + "\n")
        self._process.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _read_message(self, deadline: float) -> dict | None:
        if self._process is None or self._process.stdout is None:
            raise MCPError("server is not running")
        stdout = self._process.stdout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPError("the search server did not answer in time")
            ready, _, _ = select.select([stdout], [], [], remaining)
            if not ready:
                continue
            line = stdout.readline()
            if not line:
                raise MCPError("the search server closed the connection")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                LOGGER.debug("ignoring non json line from mcp server: %s", line[:120])
                continue

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        request_id = self._next_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            message = self._read_message(deadline)
            if message is None or message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"] or {}
                raise MCPError(str(error.get("message") or error))
            return message.get("result") or {}

    # ------------------------------------------------------------------ tools

    def list_tools(self) -> list[dict]:
        result = self._request("tools/list", {})
        return list(result.get("tools") or [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict:
        return self._request("tools/call", {"name": name, "arguments": arguments})


@dataclass
class SearchResult:
    text: str = ""
    sources: list[Source] = field(default_factory=list)
    ok: bool = True


def clean_url(url: str) -> str:
    return (url or "").strip().strip("<>").rstrip(".,;:)]}\"'")


def is_source_url(url: str) -> bool:
    """A real page the user can open, not a stylesheet or a search results page."""
    url = clean_url(url)
    if not url.startswith(("http://", "https://")):
        return False
    parts = urlparse(url)
    host = _bare_host(parts.netloc)
    if not host or host in _NOT_A_SOURCE_HOSTS:
        return False
    path = parts.path.lower()
    if path.endswith(_ASSET_SUFFIXES):
        return False
    return not any(path.startswith(prefix) for prefix in _NOT_A_SOURCE_PATHS)


def clean_title(title: str) -> str:
    """Strip the numbering, the `(source:` markers and any scraped CSS/HTML."""
    text = _MARKUP.sub(" ", title or "")
    text = re.sub(r"^[\s#>*\-–—]+", "", text)
    text = re.sub(r"^\(?\s*source\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip("()[]<>\"'`*_ ")
    if not text or "{" in text or "}" in text or ":root" in text or "var(--" in text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if len(text) > 160:
        text = text[:157].rstrip() + "..."
    return text


def host_of(url: str) -> str:
    try:
        return urlparse(clean_url(url)).netloc.lower()
    except ValueError:
        return ""


def _bare_host(netloc: str) -> str:
    host = (netloc or "").lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def extract_sources(text: str, limit: int = SOURCE_LIMIT) -> list[Source]:
    """Pull the result list out of whatever the server printed.

    The server answers with numbered results (`1. Title` then `   https://...`),
    markdown links, or bare URLs. Anything that is not an openable page (search
    engines, stylesheets, scraped CSS) is skipped instead of being listed as a
    source, and a title is never the URL when the page has one.
    """
    sources: list[Source] = []
    seen: set[str] = set()

    def add(title: str, url: str) -> None:
        url = clean_url(url)
        if len(sources) >= limit or url in seen or not is_source_url(url):
            return
        seen.add(url)
        sources.append(Source(title=clean_title(title) or host_of(url) or url, url=url))

    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        item = _LIST_ITEM.match(line)
        if item is None:
            continue
        body = item.group("body")
        link = _MD_LINK.search(body)
        if link is not None:
            add(link.group(1), link.group(2))
            continue
        inline = _URL.search(body)
        if inline is not None and inline.start() == 0:
            add(body[inline.end() :], inline.group(0))
            continue
        following = lines[index + 1].strip() if index + 1 < len(lines) else ""
        bare = _BARE_URL.match(following)
        if bare is not None:
            add(body, bare.group("url"))

    for match in _MD_LINK.finditer(text or ""):
        add(match.group(1), match.group(2))
    for index, line in enumerate(lines):
        bare = _BARE_URL.match(line.strip())
        if bare is not None:
            add(_title_above(lines, index), bare.group("url"))
    for match in _URL.finditer(text or ""):
        line_start = (text or "").rfind("\n", 0, match.start()) + 1
        add((text or "")[line_start : match.start()], match.group(0))
    return sources


def _title_above(lines: list[str], index: int) -> str:
    for previous in range(index - 1, -1, -1):
        candidate = lines[previous].strip()
        if not candidate:
            continue
        if _BARE_URL.match(candidate) or _URL.search(candidate):
            continue
        return candidate
    return ""


def scrub_citations(text: str, sources: list[Source]) -> str:
    """Drop [n] markers that do not point at a real source."""
    count = len(sources)

    def replace(match: re.Match) -> str:
        index = int(match.group(1))
        return "" if index == 0 or index > count else match.group(0)

    return re.sub(r"\[(\d{1,2})\]", replace, text or "")


class Budget:
    def __init__(self, max_calls: int | None = None, seconds: float = TOOL_DEADLINE) -> None:
        self.max_calls = MAX_TOOL_CALLS if max_calls is None else max_calls
        self.deadline = time.monotonic() + seconds
        self.calls = 0

    def take(self) -> bool:
        if self.calls >= self.max_calls or time.monotonic() > self.deadline:
            return False
        self.calls += 1
        return True


class WebSearch:
    """Tool provider for the agent, tolerant of a missing server."""

    def __init__(self, settings: config.Settings, client: MCPClient | None = None) -> None:
        self.settings = settings
        self._client = client
        self._tools: list[ToolSpec] | None = None
        self.error: str | None = None

    def start(self) -> bool:
        if not self.settings.mcp_enabled:
            self.error = "web search is disabled in settings"
            return False
        if self._client is None:
            command, env = config.resolved_mcp(self.settings)
            if not command or not Path(command[0]).is_file():
                self.error = f"{command[0] if command else 'mcp'} is not installed"
                return False
            self._client = MCPClient(command, env=env)
        try:
            self._client.start()
        except (MCPError, OSError) as exc:
            self.error = str(exc)
            return False
        return True

    def tools(self) -> list[ToolSpec]:
        if self._tools is not None:
            return self._tools
        self._tools = []
        if self._client is None:
            return self._tools
        try:
            for tool in self._client.list_tools():
                schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
                self._tools.append(
                    ToolSpec(
                        name=tool.get("name", ""),
                        description=tool.get("description", ""),
                        parameters=schema,
                    )
                )
        except MCPError as exc:
            self.error = str(exc)
        return self._tools

    def call(self, name: str, arguments: dict[str, Any]) -> SearchResult:
        if self._client is None:
            return SearchResult(text="web search is not available", ok=False)
        try:
            result = self._client.call_tool(name, arguments)
        except MCPError as exc:
            self.error = str(exc)
            return SearchResult(text=f"search failed: {exc}", ok=False)
        chunks = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(item.get("text", ""))
        text = "\n".join(chunk for chunk in chunks if chunk)
        if not text and result.get("structuredContent"):
            text = json.dumps(result["structuredContent"])[:4000]
        return SearchResult(
            text=text or "the search server returned no text",
            sources=extract_sources(text),
            ok=not result.get("isError"),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def probe_server(settings: config.Settings, handshake: bool = False) -> tuple[bool, str]:
    """Availability check used by doctor.

    Cheap by default: it only proves the command exists. `handshake=True`
    starts the server and lists its tools, which is what actually fails when
    Node, the npm package or the browser are broken.
    """
    if not settings.mcp_enabled:
        return False, "disabled in settings"
    command, _ = config.resolved_mcp(settings)
    if not command:
        return False, "no command configured"
    if not Path(command[0]).is_file():
        return False, f"{command[0]} not installed"
    if not handshake:
        return True, " ".join(command)
    web = WebSearch(settings)
    if not web.start():
        return False, f"{web.error or 'the server did not start'}"
    try:
        tools = [tool.name for tool in web.tools()]
    finally:
        web.close()
    if not tools:
        return False, web.error or "the server exposes no tools"
    return True, f"{' '.join(command)} (tools: {', '.join(tools)})"
