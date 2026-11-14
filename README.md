# Chinchilla

Select part of your screen, ask a vision model about it.

Press `Ctrl+Alt+A`, drag a box, and a panel opens with **Translate**,
**Explain**, **Fix grammar** and a free prompt box. Keep the conversation
going, add more screen cuts, switch between saved sessions.

Built for Linux desktops (GNOME/Wayland tested), no terminal required.

## Status

Under construction. See [`docs/PLAN.md`](docs/PLAN.md) for the build order and
[`docs/wireframes/wireframes.html`](docs/wireframes/wireframes.html) for the UI.

## Development

```bash
uv venv --system-site-packages      # PyGObject/GTK come from the system
uv pip install -e .
.venv/bin/python -m chinchilla version
.venv/bin/python -m chinchilla doctor
```
