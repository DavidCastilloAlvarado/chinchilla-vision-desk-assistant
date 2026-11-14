# Chinchilla

Select part of your screen, ask a vision model about it.

Press `Ctrl+Alt+A`, drag a box, and a panel opens with **Translate**,
**Explain**, **Fix grammar** and a free prompt box. Keep the conversation
going, add more screen cuts, switch between saved sessions.

Built for Linux desktops (GNOME/Wayland tested), no terminal required.

## Status

New here? Jump to [Installation](#installation).

Feature complete through the build order in [`docs/PLAN.md`](docs/PLAN.md).
Design source of truth: [`docs/wireframes/wireframes.html`](docs/wireframes/wireframes.html).

## Installation

Chinchilla is a GTK 3 desktop app. GTK, PyGObject and the screenshot portal
must come from the system (they cannot be pip-installed); the Python code and
its two libraries live in a virtualenv.

Tested on Ubuntu 24.04 with GNOME 46 on Wayland. Other GNOME distributions with
GTK 3 and `xdg-desktop-portal` should work; KDE and plain window managers are
untested.

### 1. Requirements

| Needed for | Version | Debian/Ubuntu package |
| --- | --- | --- |
| Runtime | Python 3.10+ | `python3` |
| The UI | PyGObject + GTK 3 typelibs | `python3-gi`, `gir1.2-gtk-3.0` |
| Silent capture | portal with the GNOME backend | `xdg-desktop-portal`, `xdg-desktop-portal-gnome` |
| The overlay on Wayland | XWayland (the UI runs on `GDK_BACKEND=x11`) | `xwayland` |
| The `Ctrl+Alt+A` binding | `gsettings` and `gsd-media-keys` | `libglib2.0-bin`, `gnome-settings-daemon` |
| Tray icon (optional) | AppIndicator typelib, plus the shell extension | `gir1.2-ayatanaappindicator3-0.1`, `gnome-shell-extension-appindicator` |
| Web search (optional) | Node.js 18+ with `npx`, and Chrome/Chromium | from [nodejs.org](https://nodejs.org) or `nodejs npm`, `google-chrome-stable` |

`python3-gi-cairo` is **not** required. The selector draws into its own cairo
surface and hands the frame to GTK as a pixbuf, so the GTK/cairo bridge is
never needed. Installing it is harmless but changes nothing today.

### 2. System packages

```bash
sudo apt update
sudo apt install -y \
  python3 python3-gi gir1.2-gtk-3.0 \
  xdg-desktop-portal xdg-desktop-portal-gnome xwayland \
  libglib2.0-bin gnome-settings-daemon \
  gir1.2-ayatanaappindicator3-0.1 gnome-shell-extension-appindicator
```

Fedora equivalents that matter: `python3-gobject`, `gtk3`,
`xdg-desktop-portal xdg-desktop-portal-gnome`, `xdg-desktop-portal-gtk`,
`glib2`, `libayatana-appindicator-gtk3`.

### 3. The app

```bash
git clone <this repository> chinchilla-auto-translate
cd chinchilla-auto-translate

uv venv --system-site-packages --python /usr/bin/python3
uv pip install -e .                # pillow + httpx
```

Two details matter here:

- `--system-site-packages` is **mandatory**: PyGObject is not on PyPI, so the
  venv has to see the distro's `gi`.
- `--python /usr/bin/python3` is **mandatory too**: without it `uv` may fetch
  its own managed CPython, whose site-packages do not contain the distro
  modules, and `import gi` fails with `ModuleNotFoundError`. Point it at the
  system interpreter that owns `python3-gi`.

Confirmed on a clean environment: that pair of flags gives
`python 3.12.3` + `gtk 3.24.41` inside the venv. `uv` itself, if missing:
`curl -LsSf https://astral.sh/uv/install.sh | sh`.

Use `uv pip install -e .`, not `uv sync`: `uv sync` rebuilds the environment
without `--system-site-packages` and drops `gi` again.

`uv pip install -e .` also creates the `chinchilla` command inside
`.venv/bin/`. Either activate the virtualenv or call it by path:

```bash
source .venv/bin/activate
chinchilla version
```

The virtualenv directory is used by the shortcut (the app stores the absolute
interpreter), so **do not move or recreate it after installing the shortcut** —
re-run `chinchilla shortcuts install` if you do.

### 4. Provider keys

Pick one provider in the settings dialog (`chinchilla settings`) and give it a
key. Keys are read from the environment, then from `.env`, then from the
credentials file written by the settings dialog.

```bash
cp .env.example .env        # or create .env next to pyproject.toml
```

```ini
# provider "openai"
OPENAI_API_KEY=sk-...

# provider "anthropic"
ANTHROPIC_API_KEY=sk-ant-...

# provider "openrouter"
OPENROUTER_API_KEY=sk-or-...

# provider "custom": any OpenAI compatible endpoint
LLM_BASE_URL=https://your-host/v1
LLM_MODEL=your-model
LLM_API_KEY=...
```

`.env` in the project root and `~/.config/chinchilla/.env` are both read; the
real environment wins over both. `.env` is git-ignored — never commit keys.

### 5. Web search (optional)

The agent can search the web through the `dsh-google-chrome-search` MCP server,
which drives a real Chrome profile. Nothing is installed globally: `npx`
fetches it on first use, so the tool only needs the three pieces below.

1. **Node with `npx`** on `PATH`, or in one of the usual places
   (`~/.local/node/bin`, `~/.volta/bin`, `~/.nvm/versions/node/*/bin`,
   `~/.fnm/...`). Chinchilla searches those itself, because `npx` is frequently
   outside a desktop session's `PATH`.
2. **Chrome or Chromium.**
3. Optional overrides, in `.env`:

```ini
WEBSEARCH_MCP_COMMAND=/home/you/.local/node/bin/npx
WEBSEARCH_MCP_ARGS=-y dsh-google-chrome-search mcp
CHROME_PATH=/usr/bin/google-chrome
GSEARCH_PROFILE=/home/you/.dsh-chrome-google
```

The search profile is a separate Chrome profile, so searches do not touch your
logged-in browser. It is created on first use; the first search is slow (npm
download, ~30 s) and later ones take a couple of seconds.
`chinchilla doctor` shows the exact command it will run.

### 6. Shortcut and autostart

```bash
chinchilla shortcuts install     # Ctrl+Alt+A, bound to this virtualenv
chinchilla shortcuts status
chinchilla shortcuts uninstall   # removes it again
```

The binding is a GNOME custom keybinding stored in `gsettings`; it applies
immediately, and `shortcuts install` refreshes it so `gsd-media-keys` picks the
change up. On a non-GNOME desktop add a shortcut by hand pointing at
`.venv/bin/python -m chinchilla capture --panel`.

To keep the tray icon and a warm process after login, add an autostart entry
(run this from the project root, `$(pwd)` fills in the absolute path):

```bash
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/chinchilla.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Chinchilla
Exec=$(pwd)/.venv/bin/python -m chinchilla daemon
X-GNOME-Autostart-enabled=true
NoDisplay=true
EOF
```

### 7. Check the installation

```bash
chinchilla doctor
```

Every line must be `ok`:

```
[ok  ] python: 3.12.3
[ok  ] gtk: 3.24.41
[ok  ] session: DISPLAY=:0, WAYLAND_DISPLAY=wayland-0
[ok  ] paths: /home/you/.local/share/chinchilla writable
[ok  ] provider: custom model=... key=env:LLM_API_KEY
[ok  ] capture: portal, portal-area, gnome-shell
[ok  ] websearch: /path/to/npx -y dsh-google-chrome-search mcp
[ok  ] screenshot: granted (app id '...')
[ok  ] shortcut: <Control><Alt>a -> .../python -m chinchilla capture --panel
```

Then press `Ctrl+Alt+A` and drag a box. Use `chinchilla doctor --verbose` for
the resolved paths and commands behind each line. The log is at
`~/.local/state/chinchilla/chinchilla.log` and every run starts with
`invoked: ...`, which is how you tell "the key never fired" from "the key fired
and the capture failed".

The first capture grants Chinchilla the portal's `screenshot` permission for
its own app id, so no dialog appears and no shutter sound plays.
`chinchilla permission` shows the state and `chinchilla permission revoke`
takes it back.

### 8. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `ModuleNotFoundError: gi` | The venv was made without `--system-site-packages`, or with a uv-managed Python that has no distro modules. Recreate it with `uv venv --system-site-packages --python /usr/bin/python3`, then `uv pip install -e .` and `chinchilla shortcuts install` again. |
| `Ctrl+Alt+A` does nothing, log has no `invoked:` | The binding is not live: `chinchilla shortcuts install`, and check nothing else owns `Ctrl+Alt+A`. |
| `invoked:` appears but the panel never opens | `chinchilla capture --panel` in a terminal to see the error; usually a missing `DISPLAY`/`xwayland`. |
| Panel opens, then "capture failed" | The portal refused. `chinchilla permission` shows the grant; `chinchilla doctor` shows which backends are available. The GNOME area selector remains as a fallback. |
| No tray icon | The AppIndicator extension is off. `gnome-extensions enable ubuntu-appindicators@ubuntu.com` (or `appindicatorsupport@rgcjonas.gmail.com` on upstream GNOME), then log out and in. The shortcut and CLI work regardless. |
| `websearch` is not ok | `npx` not found or Chrome missing. Set `WEBSEARCH_MCP_COMMAND` / `CHROME_PATH` in `.env`. |
| Nothing is drawn over the screen | `python3-gi-cairo` missing **and** an old checkout: the current build does not need it. Update the code and `uv pip install -e .` again. |
| Blurry or misplaced overlay | A second monitor with a different scale, or a leftover instance. `pgrep -af "chinchilla capture"`, then `kill <pid>`. |

### 9. Uninstall

```bash
chinchilla shortcuts uninstall
rm -f ~/.config/autostart/chinchilla.desktop
rm -rf .venv
rm -rf ~/.config/chinchilla ~/.local/share/chinchilla ~/.local/state/chinchilla
```

The last line also deletes your sessions, captures and saved keys.

## Use

```bash
chinchilla shortcuts install     # Ctrl+Alt+A -> chinchilla capture --panel
                                 # (reinstall after moving the checkout)
chinchilla daemon                # tray icon, no capture (use it at login)
chinchilla capture --panel       # capture a region and open the panel
chinchilla settings              # language, quick actions, providers, web, data
chinchilla sessions list         # stored conversations
chinchilla doctor                # environment, provider, capture and shortcut state
```

Inside the panel: `Ctrl+R` adds another cut, `Ctrl+N` starts a session,
`Ctrl+S` opens the session selector, `Ctrl+W` toggles web search, `Esc` hides.

### The capture flow

1. `Ctrl+Alt+A` hides the panel and takes a silent full-screen frame through
   the XDG portal (`xdg-desktop-portal` asks for the *screenshot* permission
   once; Chinchilla records the grant itself, see below).
2. Chinchilla's own selector opens over that frozen frame: everything outside
   the drag is dimmed, the selection stays bright, with a border, round grips
   on the corners and edge midpoints, a size badge and a loupe.
   `Enter` confirms, `Esc` cancels, the arrow keys nudge (`Shift` = 10 px).
3. The region is cropped, added to the session and the panel comes back.

No desktop selector and no shutter sound are involved. If the portal refuses
the silent grab (no permission store, another desktop), Chinchilla falls back
to the desktop's own area picker and says so in the panel status.

#### The screenshot permission

GNOME only answers a non-interactive screenshot for an app id that already owns
the `screenshot` permission, and it derives that id from the systemd scope the
process runs in. `chinchilla permission` shows the state, and the app grants
itself once (for its own id only) so the hotkey never opens a dialog:

```bash
chinchilla permission            # granted (app id 'com.example.Terminal')
chinchilla permission revoke     # ask the desktop again on the next capture
```

### Web search

The agent can call `search`, `fetch` and `search_and_fetch` through the same
MCP server the other desktop project uses:

```
npx -y dsh-google-chrome-search mcp
```

Chinchilla looks for `npx` on `PATH` and in `~/.local/node/bin`, `~/.nvm`,
`~/.fnm`, `~/.volta` and `~/.bun`, so an nvm/local Node install works without
touching your shell profile. The node directory is prepended to the server's
`PATH` because the package shebang is `/usr/bin/env node`.

Change the command in **Settings → Web**, point `CHROME_PATH` at your browser
(default `/usr/bin/google-chrome`) and set `GSEARCH_PROFILE` if the searches
should use a specific profile (default `~/.dsh-chrome-google`). These overrides
are also read from the environment and from `.env`:

```
WEBSEARCH_MCP_COMMAND=/home/me/.local/node/bin/npx
WEBSEARCH_MCP_ARGS=-y dsh-google-chrome-search mcp
CHROME_PATH=/usr/bin/google-chrome
GSEARCH_PROFILE=~/.dsh-chrome-google
```

`chinchilla doctor --verbose` prints the resolved command, browser and profile.
A turn may call the tools four times, twenty seconds in total; sources are
shown under the answer and cited in the text.

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
  The silent screenshot needs the portal permission; Chinchilla grants it for
  its own app id and `chinchilla permission revoke` takes it back.
- GTK here has no cairo paint context (`python3-gi-cairo` is not installed on
  every host), so the selector draws each frame into a cairo image surface and
  hands it to a `Gtk.Image` as a pixbuf. The live frame is drawn with red and
  blue swapped because cairo stores pixels as BGRA while the pixbuf reads RGBA;
  `render_to_png` turns the swap off.
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