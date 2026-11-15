"""Colours and widget styles shared by the overlay, panel and dialogs.

The values come from ``docs/wireframes/wireframes.html`` so the running app and
the wireframe cannot drift apart.
"""

# wireframe palette
BG = "#0b0d11"
INK = "#10141a"
SURFACE = "#14171d"
SURFACE_ALT = "#171b22"
SURFACE_RAISED = "#1c212b"
BORDER = "#262b35"
BORDER_SOFT = "#2a3140"
TEXT = "#e6e9ef"
TEXT_MUTED = "#7d879a"
TEXT_DIM = "#6f7a8e"
ACCENT = (0.941, 0.706, 0.161)
ACCENT_HEX = "#f0b429"
TRANSLATE = "#4c8dff"
EXPLAIN = "#a78bfa"
GRAMMAR = "#34d399"
SUCCESS = GRAMMAR
DANGER = "#f87171"
INFO = "#9aa3b3"

CSS = f"""
window {{ background-color: {SURFACE}; }}
window.chinchilla-panel {{ background-color: {SURFACE}; }}
.panel-frame {{
  background-color: {SURFACE};
  border: 1px solid #2c333f;
  border-radius: 13px;
}}
.panel-root {{ background-color: {SURFACE}; }}

/* ------------------------------------------------------------- scrollbars */
scrollbar {{ background-color: transparent; border: none; }}
scrollbar trough {{ background-color: transparent; border: none; }}
scrollbar slider {{
  background-color: #3c4557;
  border: none;
  border-radius: 3px;
  min-width: 5px;
  min-height: 24px;
}}
scrollbar slider:hover {{ background-color: #4b5568; }}
scrollbar button {{ min-width: 0; min-height: 0; padding: 0; background: none; border: none; }}

/* ------------------------------------------------------------------ header */
.panel-head {{
  background-color: {SURFACE_ALT};
  border-bottom: 1px solid #232935;
  padding: 10px 10px 10px 12px;
}}
button.head-title {{
  background-image: none;
  background-color: transparent;
  border: none;
  padding: 0;
  color: {TEXT};
  font-size: 12px;
  font-weight: 600;
}}
button.head-title:hover {{ color: #ffffff; }}
label.head-title {{ color: {TEXT}; font-size: 12px; font-weight: 600; }}
label.head-caret {{ color: {TEXT_DIM}; font-size: 8px; }}
label.head-sub {{ color: {TEXT_MUTED}; font-size: 10.5px; }}
button.icon-btn {{
  background-image: none;
  background-color: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  min-width: 24px;
  min-height: 24px;
  padding: 0;
  color: #8b93a3;
  font-size: 12px;
}}
button.icon-btn:hover {{ background-color: #232a35; border-color: #2f3745; color: {TEXT}; }}
button.icon-gear {{
  min-width: 28px;
  min-height: 28px;
  font-size: 17px;
  color: #aab4c6;
}}
button.icon-gear:hover {{ background-color: #232a35; border-color: #2f3745; color: #ffffff; }}
button.icon-close {{
  min-width: 30px;
  min-height: 30px;
  font-size: 22px;
  color: {DANGER};
}}
button.icon-close:hover {{ background-color: #3a1d22; border-color: #6b2a2f; color: #ffa1a1; }}
.thumb {{ border: 1px solid #333c4b; border-radius: 4px; }}
.thumb-behind {{ background-color: #1e2632; border: 1px solid #2f3846; border-radius: 5px; }}
label.thumb-count {{
  background-color: #2b3f6b;
  border: 1px solid #3f5b93;
  border-radius: 4px;
  color: #d7e3ff;
  font-size: 8px;
  font-weight: 600;
  padding: 0 3px;
}}

/* ------------------------------------------------------------------- tools */
.toolrow {{ padding: 9px 12px 0; }}
button.tool {{
  background-image: none;
  background-color: #1b212a;
  border: 1px solid {BORDER_SOFT};
  border-radius: 6px;
  color: #a9b2c2;
  font-size: 10.5px;
  padding: 0 9px;
  min-height: 23px;
}}
button.tool:hover {{ border-color: #3a4354; color: #dfe5f0; }}
button.tool.on {{ background-color: #1a2333; border-color: #2b3f6b; color: #dbe6ff; }}
/* Adwaita paints an orange keyboard ring on the last clicked button; the
   selected state of these chips already says where the focus is. */
button.tool:focus, button.act:focus, button.foot-btn:focus, button.set-tab:focus,
button.set-switch:focus, button.ghost-button:focus {{
  outline: none;
  box-shadow: none;
}}
button.tool:focus {{ border-color: #2b3f6b; }}
button.act:focus {{ border-color: #2b3f6b; }}
label.tool-key {{ color: #7b8497; font-size: 9px; }}
.tool-switch {{ border-radius: 999px; background-color: #3a4254; min-width: 20px; min-height: 11px; }}
.tool-switch.on {{ background-color: {TRANSLATE}; }}
.tool-knob {{ border-radius: 999px; background-color: #ffffff; min-width: 8px; min-height: 8px; margin: 1px; }}

/* ----------------------------------------------------------------- actions */
button.act {{
  background-image: none;
  background-color: {SURFACE_RAISED};
  border: 1px solid {BORDER_SOFT};
  border-radius: 8px;
  padding: 7px 9px;
  color: #d7dce6;
}}
button.act:hover {{ border-color: #3a4354; background-color: #212734; }}
button.act.active {{ border-color: {TRANSLATE}; color: #ffffff; }}
button.act.active.act-explain {{ border-color: {EXPLAIN}; }}
button.act.active.act-grammar {{ border-color: {GRAMMAR}; }}
label.act-name {{ font-size: 11.5px; font-weight: 500; color: #d7dce6; }}
label.act-key {{ font-size: 9.5px; color: #7b8497; }}
.glyph {{ border-radius: 4px; min-width: 14px; min-height: 14px; }}
.glyph-translate {{ background-color: {TRANSLATE}; }}
.glyph-explain {{ background-color: {EXPLAIN}; }}
.glyph-grammar {{ background-color: {GRAMMAR}; }}

/* ------------------------------------------------------------------ thread */
label.who {{ font-size: 9px; font-weight: 600; color: {TEXT_DIM}; }}
label.who-translate {{ color: {TRANSLATE}; }}
label.who-explain {{ color: {EXPLAIN}; }}
label.who-grammar {{ color: {GRAMMAR}; }}
label.tstamp {{ font-size: 9.5px; color: #5f6a7c; }}
label.turn-body {{ font-size: 12px; color: #dde2eb; }}
label.turn-note {{ font-size: 10.5px; color: {TEXT_MUTED}; }}
.avatar {{
  border-radius: 5px;
  min-width: 17px;
  min-height: 17px;
  font-size: 8px;
  font-weight: 800;
}}
.avatar-user {{ background-color: #2b3444; border: 1px solid #3a4557; color: #9aa3b3; }}
.avatar-ai {{ background-color: {ACCENT_HEX}; color: #14161a; }}
.crop-mini {{ border: 1px solid #3a4658; border-radius: 6px; }}
label.crop-size {{
  background-color: rgba(8, 10, 14, 0.8);
  border-radius: 3px;
  color: #b6c0d0;
  font-size: 7px;
  font-weight: 600;
  padding: 0 3px;
}}
.divider {{ background-color: #232935; min-height: 1px; }}
label.sources-head {{ font-size: 9px; font-weight: 600; color: {TEXT_DIM}; }}
label.source-label {{ font-size: 10.5px; color: #9aa9c2; }}

/* ---------------------------------------------------------------- composer */
.ask {{
  background-color: #12161d;
  border: 1px solid {BORDER_SOFT};
  border-radius: 8px;
  padding: 0 5px 0 10px;
}}
.ask.filled {{ background-color: #161b24; border-color: #3a4354; }}
.ask.ask-focus {{ border-color: #4c6ea8; }}
entry.ask-entry {{
  background-image: none;
  background-color: transparent;
  border: none;
  box-shadow: none;
  color: #dfe5f0;
  font-size: 11.5px;
  padding: 0;
  min-height: 20px;
}}
entry.ask-entry:focus {{ background-color: transparent; border: none; }}
entry.ask-entry placeholder {{ color: #6f7a8e; }}
button.send-btn {{
  background-image: none;
  background-color: {ACCENT_HEX};
  border: none;
  border-radius: 5px;
  color: #14161a;
  font-size: 11px;
  font-weight: 700;
  min-width: 22px;
  min-height: 22px;
  padding: 0;
}}
button.send-btn:hover {{ background-color: #f0bd54; }}
button.send-btn:disabled {{ background-color: #2a3040; color: #6f7a8e; }}
label.hint-label {{ color: #5f6a7c; font-size: 9.5px; }}
label.ask-placeholder {{ color: #6f7a8e; font-size: 11.5px; }}

/* ------------------------------------------------------------------ footer */
.panel-foot {{
  background-color: {SURFACE_ALT};
  border-top: 1px solid #232935;
  padding: 8px 12px;
}}
label.foot-text {{ color: {TEXT_MUTED}; font-size: 10.5px; }}
label.foot-usage {{ color: #5f6a7c; font-size: 9.5px; }}
button.foot-btn {{
  background-image: none;
  background-color: #1f252f;
  border: 1px solid #2c3340;
  border-radius: 5px;
  color: #c3cad8;
  font-size: 10.5px;
  padding: 2px 7px;
  min-height: 0;
}}
button.foot-btn:hover {{ border-color: #3a4354; color: {TEXT}; }}
button.foot-btn.primary {{ background-color: {ACCENT_HEX}; border-color: {ACCENT_HEX}; color: #14161a; font-weight: 600; }}
combobox.effort-combo {{
  background-image: none;
  background-color: #1f252f;
  border: 1px solid #2c3340;
  border-radius: 5px;
  color: #c3cad8;
  font-size: 10px;
  padding: 0 2px;
  min-height: 18px;
}}
combobox.effort-combo:hover {{ border-color: #3a4354; }}
combobox.effort-combo button {{
  background-image: none;
  background-color: transparent;
  border: none;
  border-radius: 5px;
  color: #c3cad8;
  font-size: 10px;
  padding: 0 4px;
  min-height: 0;
  box-shadow: none;
  outline: none;
}}
combobox.effort-combo arrow {{ color: {TEXT_MUTED}; min-width: 9px; min-height: 9px; }}

/* --------------------------------------------------------------- reasoning */
expander.reasoning-block {{
  margin-top: 2px;
  margin-bottom: 2px;
}}
expander.reasoning-block > title {{
  color: #6f7a8e;
  padding: 0;
  min-height: 0;
}}
expander.reasoning-block > title:hover {{ color: {TEXT_MUTED}; }}
label.reasoning-body {{
  color: #8b95a7;
  font-size: 11px;
  border-left: 2px solid #2c3340;
  padding-left: 6px;
}}

/* ----------------------------------------------------------- copilot login */
label.copilot-code {{
  font-family: monospace;
  font-size: 22px;
  letter-spacing: 3px;
  color: {TEXT};
  background-color: #1b2028;
  border: 1px solid #2c3340;
  border-radius: 6px;
  padding: 4px 10px;
}}
label.copilot-link {{ color: {INFO}; font-size: 11.5px; }}

/* ----------------------------------------------------------- generic bits */
label.muted-label {{ color: {TEXT_MUTED}; font-size: 10.5px; }}
label.body-label {{ color: #dde2eb; font-size: 12px; }}
label.title-label {{ color: {TEXT}; font-weight: 600; }}
.error-text {{ color: {DANGER}; }}
.busy-text {{ color: {INFO}; }}
.active-session {{ color: {TRANSLATE}; }}
.card {{
  background-color: {SURFACE_ALT};
  border: 1px solid {BORDER};
  border-radius: 8px;
  padding: 8px 10px;
}}
.user-card {{
  background-color: #1b222c;
  border: 1px solid #2f3846;
  border-radius: 8px;
  padding: 8px 10px;
}}
button.pill {{
  background-image: none;
  background-color: {SURFACE_RAISED};
  border: 1px solid {BORDER_SOFT};
  border-radius: 999px;
  padding: 4px 10px;
  color: {TEXT};
  font-size: 11px;
}}
button.pill:hover {{ border-color: {ACCENT_HEX}; }}
button.accent-button {{
  background-image: none;
  background-color: {ACCENT_HEX};
  color: #17130a;
  border: none;
  border-radius: 6px;
  padding: 6px 12px;
  font-weight: 600;
}}
button.accent-button:hover {{ background-color: #f0bd54; }}
button.ghost-button {{
  background-image: none;
  background-color: transparent;
  color: {TEXT_MUTED};
  border: 1px solid {BORDER};
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 11px;
}}
button.ghost-button:hover {{ color: {TEXT}; border-color: {ACCENT_HEX}; }}

/* ------------------------------------------------------- session selectors */
popover {{ background-color: {SURFACE}; border: 1px solid #2e3542; border-radius: 11px; }}
popover box {{ background-color: transparent; }}
list, list row {{ background-color: transparent; }}
.pop-head {{ background-color: #171c23; border-bottom: 1px solid #232a35; padding: 9px 10px; }}
label.pop-title {{ font-size: 9.5px; font-weight: 600; color: #8b93a3; }}
button.pop-new {{
  background-image: none;
  background-color: {ACCENT_HEX};
  border: none;
  border-radius: 5px;
  color: #14161a;
  font-size: 10.5px;
  font-weight: 600;
  padding: 4px 9px;
}}
entry.sp-search {{
  background-color: {INK};
  border: 1px solid {BORDER_SOFT};
  border-radius: 6px;
  color: {TEXT};
  font-size: 10.5px;
  padding: 3px 8px;
  min-height: 21px;
}}
button.sp-row {{
  background-image: none;
  background-color: transparent;
  border: none;
  border-radius: 0;
  padding: 7px 10px;
}}
button.sp-row:hover {{ background-color: #1b222c; }}
button.sp-row.on {{ background-color: #1b2432; border-left: 2px solid {TRANSLATE}; }}
label.sp-title {{ font-size: 11.5px; font-weight: 600; color: {TEXT}; }}
label.sp-preview {{ font-size: 10px; color: {TEXT_MUTED}; }}
label.sp-time {{ font-size: 9.5px; color: #6b7688; }}
.sp-foot {{ background-color: #171c23; border-top: 1px solid #232a35; padding: 7px 10px; }}
label.sp-foot-text {{ font-size: 10px; color: {TEXT_MUTED}; }}

/* ------------------------------------------------------------------ dialog */
window.settings {{ background-color: #14181f; }}
.set-head {{ background-color: #171c23; border-bottom: 1px solid #232a35; padding: 12px 16px; }}
.set-logo {{
  background-image: linear-gradient(145deg, #f0b429, #d99214);
  color: #14161a;
  font-weight: 800;
  font-size: 11px;
  border-radius: 5px;
  padding: 2px 6px;
}}
label.set-title {{ font-size: 13px; font-weight: 600; color: {TEXT}; }}
button.set-tab {{
  background-image: none;
  background-color: transparent;
  border: none;
  border-radius: 6px;
  color: #8b93a3;
  font-size: 11px;
  padding: 4px 9px;
}}
button.set-tab:hover {{ color: {TEXT}; }}
button.set-tab.on {{ background-color: #262d39; color: {TEXT}; }}
.set-body {{ background-color: #14181f; padding: 14px 16px 16px; }}
label.set-lbl {{ font-size: 11.5px; color: #a7b0c0; }}
label.set-section {{
  font-size: 10px;
  font-weight: 700;
  color: #7b8497;
  padding-top: 4px;
}}
label.set-note {{ font-size: 10px; color: #6b7688; }}
.set-foot {{ background-color: #171c23; border-top: 1px solid #232a35; padding: 11px 16px; }}
button.set-button {{
  background-image: none;
  background-color: transparent;
  border: 1px solid #2c3340;
  border-radius: 7px;
  color: #c3cad8;
  font-size: 11.5px;
  padding: 6px 12px;
}}
button.set-button:hover {{ border-color: {ACCENT_HEX}; color: {TEXT}; }}
button.set-button.primary {{
  background-color: {ACCENT_HEX};
  border-color: {ACCENT_HEX};
  color: #14161a;
  font-weight: 600;
}}
button.set-button.primary:hover {{ background-color: #f0bd54; }}
.settings entry {{
  background-image: none;
  background-color: #10141a;
  border: 1px solid #2a3140;
  border-radius: 7px;
  color: #dfe5f0;
  font-size: 11.5px;
  padding: 4px 10px;
  min-height: 21px;
}}
.settings entry:focus {{ border-color: {ACCENT_HEX}; }}
.settings textview {{
  background-image: none;
  background-color: #10141a;
  padding: 4px 6px;
  color: #dfe5f0;
  border: 1px solid #2a3140;
  border-radius: 7px;
  font-size: 11px;
}}
.settings textview text {{ background-image: none; background-color: #10141a; color: #dfe5f0; }}
.settings spinbutton {{
  background-image: none;
  background-color: #10141a;
  border: 1px solid #2a3140;
  border-radius: 7px;
  color: #dfe5f0;
}}
button.set-switch {{
  background-image: none;
  background-color: transparent;
  border: none;
  border-radius: 999px;
  padding: 0;
  min-width: 0;
  min-height: 0;
}}
button.set-switch:hover {{ background-color: transparent; }}
.set-switch-track {{ background-color: #3a4254; border-radius: 999px; padding: 2px; }}
.set-switch-track.on {{ background-color: {ACCENT_HEX}; }}
.set-switch-knob {{ background-color: #ffffff; border-radius: 999px; }}
.settings radiobutton radio {{
  -gtk-icon-source: none;
  background-image: none;
  background-color: #171c23;
  border: 1px solid #4b5566;
  border-radius: 999px;
  min-width: 12px;
  min-height: 12px;
}}
.settings radiobutton radio:checked {{
  -gtk-icon-source: none;
  background-image: none;
  background-color: {ACCENT_HEX};
  border-color: {ACCENT_HEX};
  box-shadow: inset 0 0 0 3px #10141a;
}}
.settings switch {{
  background-image: none;
  background-color: #3a4254;
  border: 1px solid #3a4254;
  border-radius: 999px;
  padding: 2px;
  min-width: 30px;
  min-height: 17px;
}}
.settings switch:checked {{ background-color: {ACCENT_HEX}; border-color: {ACCENT_HEX}; }}
.settings switch slider {{
  background-image: none;
  background-color: #ffffff;
  border: none;
  border-radius: 999px;
  min-width: 13px;
  min-height: 13px;
}}
.settings spinbutton button {{
  background-image: none;
  background-color: transparent;
  border: none;
  color: #a7b0c0;
  padding: 0 4px;
}}
.settings spinbutton button:hover {{ color: {TEXT}; }}
.settings radiobutton {{ color: {TEXT}; font-size: 11.5px; }}
.settings scrolledwindow {{ border: none; }}

/* ------------------------------------------------------------------ legacy */
textview.composer {{
  background-color: {INK};
  color: {TEXT};
  border: 1px solid {BORDER};
  border-radius: 6px;
}}
textview.composer text {{ background-color: {INK}; color: {TEXT}; }}
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
