# Chinchilla

Select part of your screen, ask a vision model about it.

Press `Ctrl+Alt+A`, drag a box, and a panel opens with **Translate**,
**Explain**, **Fix grammar** and a free prompt box. Keep the conversation
going, add more screen cuts, switch between saved sessions.

Built for Linux desktops (GNOME/Wayland tested), no terminal required.

## Status

Feature complete through the build order in [`docs/PLAN.md`](docs/PLAN.md).
Design source of truth: [`docs/wireframes/wireframes.html`](docs/wireframes/wireframes.html).

## Install

GTK 3 and PyGObject come from the system packages; everything else lives in a
virtualenv created with `uv`.

```bash
uv venv --system-site-packages
uv pip install -e .
```

Providers are configured with environment variables, either exported in your
shell or written to `.env` in the project root:

```bash
OPENAI_API_KEY=...            # provider "openai"
ANTHROPIC_API_KEY=...         # provider "anthropic"
OPENROUTER_API_KEY=...        # provider "openrouter"

LLM_BASE_URL=https://host/v1  # provider "custom" (OpenAI compatible)
LLM_MODEL=model-name
LLM_API_KEY=...
```

Keys can also be saved from the settings dialog; environment variables win.

## Use

```bash
chinchilla shortcuts install     # Ctrl+Alt+A -> chinchilla capture --panel
chinchilla daemon                # tray icon, no capture (use it at login)
chinchilla capture --panel       # capture a region and open the panel
chinchilla settings              # language, quick actions, providers, web, data
chinchilla sessions list         # stored conversations
chinchilla doctor                # environment, provider, capture and shortcut state
```

Inside the panel: `Ctrl+R` adds another cut, `Ctrl+N` starts a session,
`Ctrl+S` opens the session selector, `Ctrl+W` toggles web search, `Esc` hides.

### Web search

The agent can call `search`, `fetch` and `search_and_fetch` through an MCP
server over stdio. The default command is:

```
npx -y dsh-google-chrome-search mcp
```

Change it in **Settings → Web**, point `CHROME_PATH` at your browser and set
`GSEARCH_PROFILE` if the searches should use a specific profile. A turn may
call the tools four times, twenty seconds in total; sources are shown under the
answer and cited in the text.

### Where things live

| What | Path |
| --- | --- |
| Settings | `~/.config/chinchilla/settings.json` |
| API keys saved from the UI | `~/.config/chinchilla/credentials.json` (mode 0600) |
| Sessions | `~/.local/share/chinchilla/sessions/<id>.json` |
| Captures | `~/.local/share/chinchilla/captures/<id>.jpg` |
| Log | `~/.local/state/chinchilla/chinchilla.log` |

## Desktop notes

- The UI runs on GTK 3. On Wayland it forces `GDK_BACKEND=x11` through
  XWayland so the overlay can be a fullscreen, always-on-top window it can
  position itself; plain Wayland toplevels cannot do that.
- Screen capture walks a backend chain (see [`docs/CAPTURE.md`](docs/CAPTURE.md)).
  The XDG portal shows a permission dialog the first time; grant it once.
- GNOME 46 ignores `Gtk.StatusIcon` unless an extension is installed, so the
  tray falls back to an AppIndicator when one is available; without either the
  shortcut and the CLI keep working.
- The palette used by the overlay, the panel and the settings dialog is in
  `chinchilla/ui/theme.py`.

## Development

```bash
uv venv --system-site-packages      # PyGObject/GTK come from the system
uv pip install -e .
.venv/bin/python -m chinchilla version
.venv/bin/python -m chinchilla doctor
.venv/bin/python -m pytest
```

UI changes are checked by rendering the real widgets to PNG:

```bash
.venv/bin/python -m chinchilla panel --render /tmp/panel.png
.venv/bin/python -m chinchilla settings --render /tmp/settings.png --page 1
.venv/bin/python -m chinchilla sessions list --render /tmp/sessions.png --demo
.venv/bin/python -m chinchilla overlay --render /tmp/overlay.png --select 120,90,320,200
```

Headless capture can be exercised with an image file instead of the screen:

```bash
CHINCHILLA_CAPTURE_SOURCE=/path/to/image.png .venv/bin/python -m chinchilla capture --out /tmp/cut.jpg
```