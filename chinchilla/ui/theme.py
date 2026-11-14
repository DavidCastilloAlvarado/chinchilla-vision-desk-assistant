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
entry.composer {{
  background-color: {INK};
  border: 1px solid {BORDER};
  border-radius: 6px;
  color: {TEXT};
  padding: 6px 8px;
}}
"""
