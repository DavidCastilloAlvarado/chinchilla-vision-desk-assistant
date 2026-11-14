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
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from .. import log
from ..store import config
from .llm import ToolSpec
from .thread import Source

LOGGER = log.get("search")
PROTOCOL_VERSION = "2024-11-05"
MAX_TOOL_CALLS = 4
TOOL_DEADLINE = 20.0

_MD_LINK = re.compile(r"\[([^\]]{1,120})\]\((https?://[^)\s]+)\)")
_URL = re.compile(r"https?://[^\s<>\)\]\"']+")


class MCPError(RuntimeError):
    pass


class MCPClient:
    """Minimal JSON-RPC client for an MCP server over stdio."""

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        timeout: float = TOOL_DEADLINE,
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


def extract_sources(text: str, limit: int = 6) -> list[Source]:
    """Pull downloadable URLs out of whatever the server printed."""
    sources: list[Source] = []
    seen: set[str] = set()
    for match in _MD_LINK.finditer(text or ""):
        title, url = match.group(1).strip(), match.group(2).strip()
        if url in seen:
            continue
        seen.add(url)
        sources.append(Source(title=title, url=url))
        if len(sources) >= limit:
            return sources
    for match in _URL.finditer(text or ""):
        url = match.group(0).rstrip(".,;:")
        if url in seen:
            continue
        seen.add(url)
        line_start = text.rfind("\n", 0, match.start()) + 1
        title = text[line_start : match.start()].strip(" -|\t")[:80] or url
        sources.append(Source(title=title, url=url))
        if len(sources) >= limit:
            break
    return sources


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
            command = list(self.settings.mcp_command)
            if not command or shutil.which(command[0]) is None:
                self.error = f"{command[0] if command else 'mcp'} is not installed"
                return False
            self._client = MCPClient(command, env=self.settings.mcp_env)
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


def probe_server(settings: config.Settings) -> tuple[bool, str]:
    """Cheap availability check used by doctor."""
    if not settings.mcp_enabled:
        return False, "disabled in settings"
    command = list(settings.mcp_command)
    if not command:
        return False, "no command configured"
    binary = shutil.which(command[0])
    if binary is None:
        return False, f"{command[0]} not installed"
    return True, " ".join(command)
