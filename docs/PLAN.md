# Chinchilla — high level plan

Chinchilla turns a screen region into a conversation with a vision model.
Press `Ctrl+Alt+A`, drag a box, and the panel opens next to it with three
quick actions (Translate, Explain, Fix grammar) plus a free prompt box.
Every conversation is a session file you can keep adding screen cuts to.

Design source of truth: [`docs/wireframes/wireframes.html`](wireframes/wireframes.html).

## Product shape

- **No terminal.** A tray icon and a global shortcut drive everything.
- **Immediate pixels.** The capture goes straight into the request; no clipboard.
- **Sessions on disk.** One JSON file per session plus JPEG captures.
- **Any provider.** OpenAI, Anthropic, OpenRouter and one custom
  OpenAI-compatible endpoint configured from `.env`.
- **Web search.** Optional MCP server (`dsh-google-chrome-search`) giving the
  agent `search` / `fetch` / `search_and_fetch` tools with citations.

## Architecture

```
                    Ctrl+Alt+A (GNOME custom shortcut)
                              |
                              v
   +----------------------- chinchilla capture ------------------------+
   |  capture backend -> full screen image -> overlay (drag box)        |
   |                       \-> crop -> new or existing session          |
   +-------------------------------+-----------------------------------+
                                   v
   +--------------------------- chinchilla panel ----------------------+
   |  session header | quick actions | thread | composer | web toggle   |
   +-------------------------------+-----------------------------------+
                                   v
   +--------------------------- core/agent.py -------------------------+
   |  prompt building -> provider adapter -> stream -> tool calls       |
   |                                   \-> core/search.py (MCP stdio)   |
   +-------------------------------------------------------------------+
                                   v
                      store/session.py  ->  ~/.local/share/chinchilla
                      store/config.py   ->  ~/.config/chinchilla
```

| Module | Responsibility |
| --- | --- |
| `chinchilla/cli.py` | Every entry point: `capture`, `panel`, `sessions`, `settings`, `doctor`, `shortcuts`, `daemon` |
| `chinchilla/paths.py` | XDG config/data/state locations |
| `chinchilla/core/geometry.py` | Rect normalisation, clamping, crop boxes |
| `chinchilla/core/capture.py` | Full-screen and area capture backends, JPEG encoding, size budget |
| `chinchilla/core/prompts.py` | Default titles/prompts of the three quick actions |
| `chinchilla/core/llm.py` | Provider adapters, SSE streaming, image encoding |
| `chinchilla/core/agent.py` | Turn loop, tool-call handling, citation scrubbing |
| `chinchilla/core/search.py` | MCP stdio client + web-search tools and budgets |
| `chinchilla/store/config.py` | Settings file, action overrides, API key lookup |
| `chinchilla/store/session.py` | Session/capture files, listing, titles |
| `chinchilla/ui/overlay.py` | Frozen-frame selection layer |
| `chinchilla/ui/panel.py` | Response panel and thread view |
| `chinchilla/ui/settings.py` | Settings dialog |
| `chinchilla/ui/tray.py` | Status icon menu |
| `chinchilla/ui/app.py` | Single-instance application wiring |

## Build order

Each step is implemented, verified, and committed to `main` on its own.

| # | Step | Verification |
| --- | --- | --- |
| 0 | Wireframes | HTML tag balance, headless render, no overflow |
| 1 | Scaffold: `pyproject.toml`, package, CLI, docs | `python -m chinchilla version`, `doctor`, pytest |
| 2 | Overlay: rubber band, size badge, magnifier, nudging, Esc | geometry unit tests + X11 window snapshot |
| 3 | Capture: backend chain, crop, JPEG budget | backend selection tests, `file` backend round trip, `doctor` |
| 4 | Panel: header, quick actions, thread, composer | X11 window snapshot vs. wireframe |
| 5 | Store: session + settings files | round-trip tests, listing, retention |
| 6 | Providers: OpenAI/Anthropic/OpenRouter/custom, streaming | fake-server tests for SSE + request shape |
| 7 | Agent: prompts, images, turns, streaming events | unit tests over a stub provider |
| 8 | Web search: MCP client, tool loop, citations | tests against a fake MCP stdio server |
| 9 | Settings UI: actions, providers, web, data | snapshot + round-trip tests |
| 10 | App: single instance, tray, shortcut install | `shortcuts status`, live smoke run |
| 11 | Docs: README, verification notes | full test suite + end-to-end run |

## Environment notes

- Wayland (GNOME 46). `gtk-layer-shell` bindings are not installed, so the UI
  runs on the X11 backend through XWayland (`GDK_BACKEND=x11` by default when an
  X display is reachable). That gives the overlay a fullscreen, always-on-top
  window it can position itself, which plain Wayland toplevels cannot do.
- Screenshot capture goes through a chain of backends, see
  [`docs/CAPTURE.md`](CAPTURE.md). The XDG portal may require a one-time
  permission prompt; `chinchilla doctor` reports what works.
- The global shortcut is a GNOME custom keybinding created by
  `chinchilla shortcuts install` (`Ctrl+Alt+A`).