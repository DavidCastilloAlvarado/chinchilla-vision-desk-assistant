"""Tiny MCP stdio server used by the search tests."""

import json
import sys

TOOLS = [
    {
        "name": "search",
        "description": "Search the web",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "fetch",
        "description": "Fetch a page",
        "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}},
    },
]

TEXT = (
    "Top results\n"
    "- [Token expiry explained](https://example.com/tokens)\n"
    "- https://example.org/retries\n"
)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        request_id = message.get("id")
        if request_id is None:
            continue
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-search", "version": "0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = message.get("params") or {}
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"{params.get('name')}({json.dumps(params.get('arguments'))})\n{TEXT}",
                    }
                ],
                "isError": False,
            }
        else:
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"unknown method {method}"},
                    }
                ),
                flush=True,
            )
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)


if __name__ == "__main__":
    main()
