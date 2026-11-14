"""Colours shared by the overlay, the panel and the settings dialog."""

ACCENT = (0.902, 0.686, 0.235)
ACCENT_HEX = "#e6af3c"
INK = "#101216"
SURFACE = "#171a20"
SURFACE_ALT = "#1e222a"
BORDER = "#2c313a"
TEXT = "#e9e6e1"
TEXT_MUTED = "#9aa1ab"
SUCCESS = "#7bbf6a"
DANGER = "#e2624b"
INFO = "#6aa8e0"

CSS = f"""
window.chinchilla-panel {{
  background-color: {SURFACE};
}}
.card {{
  background-color: {SURFACE_ALT};
  border: 1px solid {BORDER};
  border-radius: 8px;
  padding: 8px 10px;
}}
.user-card {{
  background-color: #232a36;
  border: 1px solid #38404f;
  border-radius: 8px;
  padding: 8px 10px;
}}
.title-label {{ color: {TEXT}; font-weight: 600; }}
.muted-label {{ color: {TEXT_MUTED}; font-size: 11px; }}
.body-label {{ color: {TEXT}; font-size: 13px; }}
.pill {{
  background-color: {SURFACE_ALT};
  border: 1px solid {BORDER};
  border-radius: 999px;
  padding: 4px 10px;
  color: {TEXT};
  font-size: 11px;
}}
.pill:hover {{ border-color: {ACCENT_HEX}; }}
.pill.suggested {{ border-color: {ACCENT_HEX}; color: {ACCENT_HEX}; }}
.accent-button {{
  background-image: none;
  background-color: {ACCENT_HEX};
  color: #17130a;
  border: none;
  border-radius: 6px;
  padding: 6px 12px;
  font-weight: 600;
}}
.accent-button:hover {{ background-color: #f0bd54; }}
.ghost-button {{
  background-image: none;
  background-color: transparent;
  color: {TEXT_MUTED};
  border: 1px solid {BORDER};
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 11px;
}}
.ghost-button:hover {{ color: {TEXT}; border-color: {ACCENT_HEX}; }}
.panel-frame {{
  background-color: {SURFACE};
  border: 1px solid {BORDER};
  border-radius: 10px;
}}
.panel-root {{ background-color: {SURFACE}; }}
button.session-title {{
  color: {TEXT};
  font-weight: 600;
  font-size: 13px;
  padding: 0;
  background-image: none;
  background-color: transparent;
  border: none;
}}
.thumb {{ border: 1px solid {BORDER}; border-radius: 3px; }}
.error-text {{ color: {DANGER}; }}
.busy-text {{ color: {INFO}; }}
.source-label {{ color: {TEXT_MUTED}; font-size: 11px; }}
textview.composer {{
  background-color: {INK};
  color: {TEXT};
  border: 1px solid {BORDER};
  border-radius: 6px;
}}
entry.composer {{
  background-color: {INK};
  border: 1px solid {BORDER};
  border-radius: 6px;
  color: {TEXT};
  padding: 6px 8px;
}}
"""


def apply_css() -> None:
    """Install the stylesheet once per process."""
    from .gtk import Gdk, Gtk

    global _installed
    if _installed:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode("utf-8"))
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    _installed = True


_installed = False
