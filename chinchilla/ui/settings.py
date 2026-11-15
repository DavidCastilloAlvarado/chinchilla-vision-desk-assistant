"""Settings dialog: language, quick actions, providers and web search."""

from __future__ import annotations

import threading
from typing import Callable

from ..core import copilot, search
from ..store import config
from . import theme
from .gtk import GLib, Gtk
from .widgets import place_knob

def _label(text: str, muted: bool = False, wrap: bool = False) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.set_xalign(0)
    if muted:
        label.get_style_context().add_class("muted-label")
    label.set_line_wrap(wrap)
    return label


def _lbl(text: str) -> Gtk.Label:
    """Left column of a settings row: 130px, like the wireframe."""
    label = _label(text)
    label.get_style_context().add_class("set-lbl")
    label.set_size_request(130, -1)
    return label


def _section(text: str) -> Gtk.Label:
    label = _label(text.upper())
    label.get_style_context().add_class("set-section")
    return label


def _entry(text: str, password: bool = False, width: int = 260) -> Gtk.Entry:
    entry = Gtk.Entry()
    entry.set_text(text or "")
    entry.set_visibility(not password)
    entry.set_width_chars(28)
    entry.set_size_request(width, -1)
    return entry


def _textview(text: str, height: int = 90) -> Gtk.TextView:
    view = Gtk.TextView()
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.get_buffer().set_text(text or "")
    view.set_size_request(-1, height)
    return view


def _scrolled(child: Gtk.Widget, height: int = 90) -> Gtk.ScrolledWindow:
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_size_request(-1, height)
    scroll.add(child)
    return scroll


def _text_of(view: Gtk.TextView) -> str:
    buffer = view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


def _key_status(provider_id: str) -> str:
    source = config.key_source(provider_id)
    if source.startswith("env:"):
        return f"key: {source} - wins over the key saved here"
    if source == "file":
        return "key: saved here"
    return "key: missing"


def _origin_note(settings: config.Settings, provider_id: str, field: str) -> str:
    """Say where the custom endpoint/model comes from, and how to change it."""
    if provider_id != "custom":
        return ""
    name = config.CUSTOM_FIELDS[field]
    env = config.env_value(name)
    if not env:
        return ""
    if field in settings.custom_explicit:
        return f"saved here; {name} from {config.env_source(name)} is ignored"
    return f"value from {config.env_source(name)} ({name}); edit it and save to override"


def _effective_entries(
    settings: config.Settings, provider_id: str, base_url: Gtk.Entry, model: Gtk.Entry
) -> dict[str, Gtk.Label]:
    """Show the value that is really in use, plus a note per overridable field."""
    if provider_id == "custom":
        effective = config.effective_provider(settings, provider_id)
        base_url.set_text((effective.base_url or "").rstrip("/"))
        model.set_text(effective.model or "")
    notes: dict[str, Gtk.Label] = {}
    for field, entry in (("base_url", base_url), ("model", model)):
        text = _origin_note(settings, provider_id, field)
        if not text:
            continue
        label = _label(text, muted=True, wrap=True)
        label.set_margin_start(24)
        notes[field] = label
        entry.set_tooltip_text(text)
    return notes


class ToggleSwitch(Gtk.Button):
    """A 30x17 switch drawn from boxes; GtkSwitch cannot be styled that small."""

    def __init__(self, active: bool = False) -> None:
        super().__init__()
        self._active = bool(active)
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.CENTER)
        self.get_style_context().add_class("set-switch")
        self._track = Gtk.Box()
        self._track.get_style_context().add_class("set-switch-track")
        self._track.set_size_request(30, 17)
        self._track.set_halign(Gtk.Align.START)
        self._track.set_valign(Gtk.Align.CENTER)
        self._knob = Gtk.Box()
        self._knob.get_style_context().add_class("set-switch-knob")
        self._knob.set_size_request(13, 13)
        self.add(self._track)
        self.connect("clicked", lambda *_: self.set_active(not self._active))
        self._render()

    def _render(self) -> None:
        context = self._track.get_style_context()
        if self._active:
            context.add_class("on")
        else:
            context.remove_class("on")
        place_knob(self._track, self._knob, self._active)

    def get_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._render()


class SettingsContent(Gtk.Box):
    """The tabbed form, separate from the window so it can be rendered."""

    PAGES = ("General", "Actions", "Providers", "Web", "Data")

    def __init__(self, settings: config.Settings, on_save: Callable[[config.Settings], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        theme.apply_css()
        self.settings = settings
        self.on_save = on_save
        self.set_size_request(600, 620)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        head.get_style_context().add_class("set-head")
        logo = Gtk.Label(label="C")
        logo.get_style_context().add_class("set-logo")
        head.pack_start(logo, False, False, 0)
        title = Gtk.Label(label="Settings")
        title.set_xalign(0)
        title.get_style_context().add_class("set-title")
        head.pack_start(title, False, False, 0)
        self.head = head
        self.head_tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        head.pack_end(self.head_tools, False, False, 0)

        self.tab_buttons: dict[str, Gtk.Button] = {}
        tabs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for name in self.PAGES:
            button = Gtk.Button(label=name)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.get_style_context().add_class("set-tab")
            button.connect("clicked", lambda _b, page=name: self.set_current_page(page))
            tabs.pack_start(button, False, False, 0)
            self.tab_buttons[name] = button
        head.pack_end(tabs, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        self.pack_start(self.stack, True, True, 0)

        self._build_general()
        self._build_actions()
        self._build_providers()
        self._build_web()
        self._build_data()

        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        foot.get_style_context().add_class("set-foot")
        self.save_statuses: list[Gtk.Label] = []
        status = Gtk.Label(label="")
        status.set_xalign(0)
        status.get_style_context().add_class("set-note")
        self.save_statuses.append(status)
        foot.pack_start(status, True, True, 0)

        self.cancel_button = Gtk.Button(label="Cancel")
        self.cancel_button.set_relief(Gtk.ReliefStyle.NONE)
        self.cancel_button.get_style_context().add_class("set-button")
        foot.pack_start(self.cancel_button, False, False, 0)
        self.save_button = Gtk.Button(label="Save")
        self.save_button.set_relief(Gtk.ReliefStyle.NONE)
        self.save_button.get_style_context().add_class("set-button")
        self.save_button.get_style_context().add_class("primary")
        self.save_button.connect("clicked", lambda *_: self.save())
        foot.pack_start(self.save_button, False, False, 0)
        self.pack_start(foot, False, False, 0)

        self.set_current_page("General")

    # ------------------------------------------------------------------ pages

    def set_current_page(self, page) -> None:
        """Show a page by name, or by index like ``settings --page 2``."""
        name = self.PAGES[page] if isinstance(page, int) else page
        self.stack.set_visible_child_name(name)
        for key, button in self.tab_buttons.items():
            context = button.get_style_context()
            if key == name:
                context.add_class("on")
            else:
                context.remove_class("on")

    def current_page(self) -> str:
        return self.stack.get_visible_child_name() or self.PAGES[0]

    def _page(self, title: str) -> Gtk.Box:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.get_style_context().add_class("set-body")
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(outer)
        self.stack.add_named(scroll, title)
        return outer

    def _build_general(self) -> None:
        page = self._page("General")
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.language_entry = _entry(self.settings.language, width=180)
        self.level_entry = _entry(self.settings.level, width=180)
        self.save_switch = ToggleSwitch()
        self.save_switch.set_active(self.settings.save_sessions)
        self.retention_spin = Gtk.SpinButton.new_with_range(0, 3650, 1)
        self.retention_spin.set_value(self.settings.retention_days)
        self.web_default_switch = ToggleSwitch()
        self.web_default_switch.set_active(self.settings.web_enabled)
        self.tokens_spin = Gtk.SpinButton.new_with_range(512, 200_000, 1024)
        self.tokens_spin.set_value(self.settings.max_tokens)
        self.tokens_spin.set_tooltip_text("output budget per answer; a thinking model needs room")
        self.effort_combo = Gtk.ComboBoxText()
        for level in config.REASONING_EFFORTS:
            self.effort_combo.append(level, level)
        self.effort_combo.set_active_id(self.settings.reasoning_effort)

        rows = [
            (_lbl("Answer language"), self.language_entry, _label("value for {language}", muted=True)),
            (_lbl("Explanation level"), self.level_entry, _label("value for {level}", muted=True)),
            (_lbl("Save sessions"), self.save_switch, _label("keep every conversation on disk", muted=True)),
            (_lbl("Retention (days)"), self.retention_spin, _label("0 keeps everything", muted=True)),
            (_lbl("Web by default"), self.web_default_switch, _label("new sessions start with search on", muted=True)),
            (
                _lbl("Max output tokens"),
                self.tokens_spin,
                _label("the answer is never cut short of this budget", muted=True),
            ),
            (
                _lbl("Reasoning effort"),
                self.effort_combo,
                _label("sent as reasoning_effort, when the endpoint knows it", muted=True),
            ),
        ]
        for index, (name, widget, hint) in enumerate(rows):
            grid.attach(name, 0, index, 1, 1)
            grid.attach(widget, 1, index, 1, 1)
            grid.attach(hint, 2, index, 1, 1)
        page.pack_start(grid, False, False, 0)

        page.pack_start(_section("Shortcut"), False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(_lbl("Capture"), False, False, 0)
        keys = self.settings.hotkey.replace("<", "").replace(">", "+").strip("+").upper()
        shortcut_entry = _entry(keys, width=180)
        shortcut_entry.set_editable(False)
        shortcut_entry.set_tooltip_text("bind chinchilla capture in GNOME Settings > Keyboard")
        row.pack_start(shortcut_entry, False, False, 0)
        row.pack_start(_label("install with: chinchilla shortcuts install", muted=True), False, False, 0)
        page.pack_start(row, False, False, 0)


    def _build_actions(self) -> None:
        page = self._page("Actions")
        page.pack_start(
            _label(
                "Every quick action has an editable title (18 characters) and prompt. "
                "Use {language}, {level}, {text} and {sources} as placeholders.",
                muted=True,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        self.action_rows: dict[str, tuple[Gtk.Entry, Gtk.TextView, Gtk.Switch]] = {}
        for action in self.settings.actions:
            page.pack_start(_section(action.id), False, False, 0)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

            title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title_entry = _entry(action.title, width=200)
            title_entry.set_max_length(18)
            web_switch = ToggleSwitch()
            web_switch.set_active(action.web_default)
            reset = Gtk.Button(label="Reset to default")
            reset.get_style_context().add_class("ghost-button")
            reset.connect("clicked", self._on_reset_action, action.id, title_entry)
            title_row.pack_start(_lbl("Title"), False, False, 0)
            title_row.pack_start(title_entry, False, False, 0)
            title_row.pack_end(reset, False, False, 0)
            title_row.pack_end(web_switch, False, False, 0)
            title_row.pack_end(_label("Web by default", muted=True), False, False, 0)
            box.pack_start(title_row, False, False, 0)

            prompt_view = _textview(action.prompt, 96)
            box.pack_start(_scrolled(prompt_view, 96), False, False, 0)
            page.pack_start(box, False, False, 0)
            self.action_rows[action.id] = (title_entry, prompt_view, web_switch)

    def _build_providers(self) -> None:
        page = self._page("Providers")
        page.pack_start(
            _label(
                "Keys come from the environment when present, otherwise from the key saved here.",
                muted=True,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        self.provider_widgets: dict[str, dict[str, Gtk.Widget]] = {}
        self.origin_notes: dict[str, dict[str, Gtk.Label]] = {}
        group = None
        for provider in self.settings.providers.values():
            radio = Gtk.RadioButton.new_with_label_from_widget(
                group, f"{provider.label}  ({provider.id})"
            )
            group = group or radio
            radio.set_active(self.settings.active_provider == provider.id)
            page.pack_start(radio, False, False, 0)
            if provider.id == "copilot":
                self._build_copilot(page, radio)
                continue

            grid = Gtk.Grid(column_spacing=10, row_spacing=6)
            grid.set_margin_start(24)
            base_url = _entry(provider.base_url or "", width=320)
            model = _entry(provider.model, width=240)
            notes = _effective_entries(self.settings, provider.id, base_url, model)
            self.origin_notes[provider.id] = notes
            key_entry = _entry("", password=True, width=320)
            status = _label(_key_status(provider.id), muted=True, wrap=True)
            save_key = Gtk.Button(label="Save key")
            save_key.get_style_context().add_class("ghost-button")
            save_key.connect("clicked", self._on_save_key, provider.id, key_entry, status)

            grid.attach(_lbl("Base URL"), 0, 0, 1, 1)
            grid.attach(base_url, 1, 0, 2, 1)
            grid.attach(_lbl("Model"), 0, 1, 1, 1)
            grid.attach(model, 1, 1, 2, 1)
            grid.attach(_lbl("API key"), 0, 2, 1, 1)
            grid.attach(key_entry, 1, 2, 1, 1)
            grid.attach(save_key, 2, 2, 1, 1)
            grid.attach(status, 1, 3, 2, 1)
            page.pack_start(grid, False, False, 0)
            for field in ("base_url", "model"):
                if field in notes:
                    page.pack_start(notes[field], False, False, 0)

            self.provider_widgets[provider.id] = {
                "radio": radio,
                "base_url": base_url,
                "model": model,
                "status": status,
            }

    def _build_copilot(self, page: Gtk.Box, radio: Gtk.RadioButton) -> None:
        self.copilot_credentials = copilot.Credentials.load()
        self.copilot_models: list[copilot.CopilotModel] = []
        self.copilot_status = _label("", muted=True, wrap=True)
        self.copilot_combo = Gtk.ComboBoxText()
        self.copilot_combo.set_size_request(240, -1)
        self.copilot_combo.set_tooltip_text("the models your Copilot subscription offers")

        self.copilot_sign_in = Gtk.Button(label="Sign in with GitHub")
        self.copilot_sign_in.set_relief(Gtk.ReliefStyle.NONE)
        self.copilot_sign_in.get_style_context().add_class("ghost-button")
        self.copilot_sign_in.connect("clicked", lambda *_: self._on_copilot_sign_in())
        self.copilot_sign_out = Gtk.Button(label="Sign out")
        self.copilot_sign_out.set_relief(Gtk.ReliefStyle.NONE)
        self.copilot_sign_out.get_style_context().add_class("ghost-button")
        self.copilot_sign_out.connect("clicked", lambda *_: self._on_copilot_sign_out())
        self.copilot_reload = Gtk.Button(label="Reload models")
        self.copilot_reload.set_relief(Gtk.ReliefStyle.NONE)
        self.copilot_reload.get_style_context().add_class("ghost-button")
        self.copilot_reload.connect("clicked", lambda *_: self._load_copilot_models())

        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        grid.set_margin_start(24)
        grid.attach(_lbl("Model"), 0, 0, 1, 1)
        grid.attach(self.copilot_combo, 1, 0, 2, 1)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.pack_start(self.copilot_sign_in, False, False, 0)
        buttons.pack_start(self.copilot_sign_out, False, False, 0)
        buttons.pack_start(self.copilot_reload, False, False, 0)
        grid.attach(buttons, 1, 1, 2, 1)
        grid.attach(self.copilot_status, 1, 2, 2, 1)
        page.pack_start(grid, False, False, 0)
        page.pack_start(
            _label(
                "Uses your GitHub Copilot subscription: the sign-in opens github.com/login/device, "
                "and the model list comes from the subscription. No API key is stored.",
                muted=True,
                wrap=True,
            ),
            False,
            False,
            0,
        )

        self.provider_widgets.setdefault("copilot", {})["radio"] = radio
        self.provider_widgets["copilot"]["model"] = self.copilot_combo
        self._refresh_copilot()

    # ---------------------------------------------------------- copilot state

    def _refresh_copilot(self) -> None:
        signed_in = self.copilot_credentials.signed_in
        self.copilot_sign_out.set_sensitive(signed_in)
        self.copilot_reload.set_sensitive(signed_in)
        if not signed_in:
            self.copilot_combo.remove_all()
            self.copilot_status.set_text("not signed in")
            return
        self.copilot_status.set_text(f"{self.copilot_credentials.describe()} \u00b7 loading models\u2026")
        self._load_copilot_models()

    def _load_copilot_models(self) -> None:
        if not self.copilot_credentials.signed_in:
            self.copilot_status.set_text("not signed in")
            return
        self.copilot_status.set_text("loading models\u2026")
        threading.Thread(target=self._copilot_models_worker, daemon=True).start()

    def _copilot_models_worker(self) -> None:
        try:
            models = copilot.list_models(self.copilot_credentials.session())
        except copilot.CopilotError as exc:
            GLib.idle_add(self.copilot_status.set_text, f"cannot list models: {exc}")
            return
        GLib.idle_add(self._copilot_models_loaded, models)

    def _copilot_models_loaded(self, models: list[copilot.CopilotModel]) -> bool:
        self.copilot_models = models
        current = self.settings.providers["copilot"].model
        self.copilot_combo.remove_all()
        for model in models:
            self.copilot_combo.append(model.id, model.label)
        wanted = current if current in {model.id for model in models} else (models[0].id if models else "")
        if wanted:
            self.copilot_combo.set_active_id(wanted)
        count = len(models)
        self.copilot_status.set_text(
            f"{self.copilot_credentials.describe()} \u00b7 {count} models"
            if count
            else "signed in, but this subscription offers no chat model"
        )
        return False

    def _on_copilot_sign_in(self) -> None:
        from .copilot_login import CopilotLoginDialog

        window = self.get_toplevel()
        dialog = CopilotLoginDialog(window if isinstance(window, Gtk.Window) else None)
        dialog.run()
        dialog.destroy()
        if dialog.credentials is not None:
            self.copilot_credentials = dialog.credentials
        elif dialog.error:
            self.copilot_status.set_text(dialog.error)
            return
        self._refresh_copilot()

    def _on_copilot_sign_out(self) -> None:
        self.copilot_credentials.clear()
        self._refresh_copilot()

    def _build_web(self) -> None:
        page = self._page("Web")
        self.mcp_switch = ToggleSwitch()
        self.mcp_switch.set_active(self.settings.mcp_enabled)
        self.mcp_command_entry = _entry(" ".join(self.settings.mcp_command), width=360)
        self.chrome_entry = _entry(self.settings.mcp_env.get("CHROME_PATH", ""), width=260)
        self.profile_entry = _entry(self.settings.mcp_env.get("GSEARCH_PROFILE", ""), width=260)
        self.probe_label = _label("", muted=True, wrap=True)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        grid.attach(_lbl("Enable web search"), 0, 0, 1, 1)
        grid.attach(self.mcp_switch, 1, 0, 1, 1)
        grid.attach(_lbl("MCP command"), 0, 1, 1, 1)
        grid.attach(self.mcp_command_entry, 1, 1, 1, 1)
        grid.attach(_lbl("CHROME_PATH"), 0, 2, 1, 1)
        grid.attach(self.chrome_entry, 1, 2, 1, 1)
        grid.attach(_lbl("GSEARCH_PROFILE"), 0, 3, 1, 1)
        grid.attach(self.profile_entry, 1, 3, 1, 1)
        page.pack_start(grid, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        probe = Gtk.Button(label="Test connection")
        probe.get_style_context().add_class("ghost-button")
        probe.connect("clicked", self._on_probe)
        row.pack_start(probe, False, False, 0)
        row.pack_start(self.probe_label, True, True, 0)
        page.pack_start(row, False, False, 0)
        page.pack_start(
            _label(
                "Tools exposed by the server: search, fetch, search_and_fetch. "
                "A turn may call them up to four times, twenty seconds in total.",
                muted=True,
                wrap=True,
            ),
            False,
            False,
            0,
        )

    def _build_data(self) -> None:
        from .. import paths

        page = self._page("Data")
        for name, value in (
            ("Settings", str(paths.settings_path())),
            ("Sessions", str(paths.sessions_dir())),
            ("Captures", str(paths.captures_dir())),
            ("Log", str(paths.log_path())),
        ):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.pack_start(_lbl(name), False, False, 0)
            row.pack_start(_label(value, muted=True), False, False, 0)
            page.pack_start(row, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        prune = Gtk.Button(label="Delete old sessions now")
        prune.get_style_context().add_class("ghost-button")
        prune.connect("clicked", self._on_prune)
        row.pack_start(prune, False, False, 0)
        self.prune_label = _label("", muted=True)
        row.pack_start(self.prune_label, True, True, 0)
        page.pack_start(row, False, False, 0)

    # ----------------------------------------------------------------- events

    def _on_reset_action(self, _button, action_id: str, title_entry: Gtk.Entry) -> None:
        defaults = {action.id: action for action in config.default_actions()}
        if action_id in defaults:
            title_entry.set_text(defaults[action_id].title)
            view = self.action_rows[action_id][1]
            view.get_buffer().set_text(defaults[action_id].prompt)

    def _on_save_key(self, _button, provider_id: str, entry: Gtk.Entry, status: Gtk.Label) -> None:
        key = entry.get_text().strip()
        if not key:
            status.set_text("paste a key first")
            return
        config.save_credential(provider_id, key)
        entry.set_text("")
        status.set_text(f"key: {config.key_source(provider_id)}")

    def _on_probe(self, _button) -> None:
        self.collect()
        ok, detail = search.probe_server(self.settings)
        if ok:
            web = search.WebSearch(self.settings)
            started = web.start()
            tools = [tool.name for tool in web.tools()] if started else []
            web.close()
            ok = started
            detail = f"tools: {', '.join(tools)}" if tools else (web.error or "no tools")
        self.probe_label.set_text(("ok - " if ok else "failed - ") + detail)

    def _on_prune(self, _button) -> None:
        from ..store import session as session_store

        removed = session_store.prune(self.settings.retention_days)
        self.prune_label.set_text(
            f"removed {removed} session(s)" if self.settings.retention_days else "set a retention window first"
        )

    # ------------------------------------------------------------------- save

    def _record_custom_sources(
        self, settings: config.Settings, provider: config.ProviderSettings
    ) -> None:
        """A value typed over the one in .env wins from now on; matching it does not."""
        explicit = set(settings.custom_explicit)
        for field, name in config.CUSTOM_FIELDS.items():
            env = config.env_value(name)
            value = getattr(provider, field) or ""
            if env and value and value.rstrip("/") != env.rstrip("/"):
                explicit.add(field)
            else:
                explicit.discard(field)
        settings.custom_explicit = [field for field in config.CUSTOM_FIELDS if field in explicit]

    def _refresh_origin_notes(self) -> None:
        for provider_id, notes in self.origin_notes.items():
            for field, label in notes.items():
                label.set_text(_origin_note(self.settings, provider_id, field))

    def collect(self) -> config.Settings:
        settings = self.settings
        settings.language = self.language_entry.get_text().strip() or config.DEFAULT_LANGUAGE
        settings.level = self.level_entry.get_text().strip() or config.DEFAULT_LEVEL
        settings.save_sessions = bool(self.save_switch.get_active())
        settings.web_enabled = bool(self.web_default_switch.get_active())
        settings.retention_days = int(self.retention_spin.get_value())
        settings.max_tokens = int(self.tokens_spin.get_value())
        settings.reasoning_effort = self.effort_combo.get_active_id() or config.DEFAULT_REASONING

        for action_id, (title_entry, prompt_view, web_switch) in self.action_rows.items():
            action = settings.action(action_id)
            if action is None:
                continue
            action.title = title_entry.get_text().strip() or action.title
            action.prompt = _text_of(prompt_view).strip() or action.prompt
            action.web_default = bool(web_switch.get_active())

        for provider_id, widgets in self.provider_widgets.items():
            provider = settings.providers[provider_id]
            if provider_id == "copilot":
                provider.model = self.copilot_combo.get_active_id() or provider.model
                if widgets["radio"].get_active():
                    settings.active_provider = provider_id
                continue
            provider.base_url = widgets["base_url"].get_text().strip().rstrip("/")
            provider.model = widgets["model"].get_text().strip()
            if provider_id == "custom":
                self._record_custom_sources(settings, provider)
            if widgets["radio"].get_active():
                settings.active_provider = provider_id

        settings.mcp_enabled = bool(self.mcp_switch.get_active())
        command = self.mcp_command_entry.get_text().strip()
        settings.mcp_command = command.split() if command else settings.mcp_command
        settings.mcp_env = {}
        if self.chrome_entry.get_text().strip():
            settings.mcp_env["CHROME_PATH"] = self.chrome_entry.get_text().strip()
        if self.profile_entry.get_text().strip():
            settings.mcp_env["GSEARCH_PROFILE"] = self.profile_entry.get_text().strip()
        return settings

    def save(self) -> config.Settings:
        settings = self.collect()
        target = config.save_settings(settings)
        self._refresh_origin_notes()
        for label in self.save_statuses:
            label.set_text(f"saved to {target.name}")
        if self.on_save is not None:
            self.on_save(settings)
        return settings


class SettingsWindow(Gtk.Window):
    def __init__(self, settings: config.Settings, on_save: Callable[[config.Settings], None] | None = None) -> None:
        super().__init__(title="Chinchilla settings")
        theme.apply_css()
        self.get_style_context().add_class("settings")
        self.set_default_size(600, 640)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.content = SettingsContent(settings, on_save)
        self.content.cancel_button.connect("clicked", lambda *_: self.close())
        close = Gtk.Button(label="\u00d7")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.get_style_context().add_class("icon-btn")
        close.get_style_context().add_class("icon-close")
        close.set_tooltip_text("Close (Esc)")
        close.connect("clicked", lambda *_: self.close())
        self.content.head_tools.pack_start(close, False, False, 0)
        self.add(self.content)
