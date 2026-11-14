"""Settings dialog: language, quick actions, providers and web search."""

from __future__ import annotations

from typing import Callable

from ..core import search
from ..store import config
from . import theme
from .gtk import Gtk

PAGE_MARGIN = 14


def _label(text: str, muted: bool = False, wrap: bool = False) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.set_xalign(0)
    if muted:
        label.get_style_context().add_class("muted-label")
    label.set_line_wrap(wrap)
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


class SettingsContent(Gtk.Notebook):
    """The tabbed form, separate from the window so it can be rendered."""

    def __init__(self, settings: config.Settings, on_save: Callable[[config.Settings], None] | None = None) -> None:
        super().__init__()
        theme.apply_css()
        self.settings = settings
        self.on_save = on_save
        self.set_size_request(560, 560)

        self._build_general()
        self._build_actions()
        self._build_providers()
        self._build_web()
        self._build_data()

    # ------------------------------------------------------------------ pages

    def _page(self, title: str) -> Gtk.Box:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_start(PAGE_MARGIN)
        outer.set_margin_end(PAGE_MARGIN)
        outer.set_margin_top(PAGE_MARGIN)
        outer.set_margin_bottom(PAGE_MARGIN)
        self.append_page(outer, Gtk.Label(label=title))
        return outer

    def _build_general(self) -> None:
        page = self._page("General")
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.language_entry = _entry(self.settings.language, width=180)
        self.level_entry = _entry(self.settings.level, width=180)
        self.save_switch = Gtk.Switch()
        self.save_switch.set_active(self.settings.save_sessions)
        self.retention_spin = Gtk.SpinButton.new_with_range(0, 3650, 1)
        self.retention_spin.set_value(self.settings.retention_days)
        self.web_default_switch = Gtk.Switch()
        self.web_default_switch.set_active(self.settings.web_enabled)

        rows = [
            (_label("Answer language"), self.language_entry, _label("value for {language}", muted=True)),
            (_label("Explanation level"), self.level_entry, _label("value for {level}", muted=True)),
            (_label("Save sessions"), self.save_switch, _label("keep every conversation on disk", muted=True)),
            (_label("Retention (days, 0 keeps)"), self.retention_spin, _label("", muted=True)),
            (_label("Web search by default"), self.web_default_switch, _label("new sessions start with search on", muted=True)),
        ]
        for index, (name, widget, hint) in enumerate(rows):
            grid.attach(name, 0, index, 1, 1)
            grid.attach(widget, 1, index, 1, 1)
            grid.attach(hint, 2, index, 1, 1)
        page.pack_start(grid, False, False, 0)

        shortcut = Gtk.Frame(label="Shortcut")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(8)
        row.set_margin_end(8)
        row.set_margin_top(6)
        row.set_margin_bottom(6)
        row.pack_start(_label("Capture"), False, False, 0)
        row.pack_start(_label(self.settings.hotkey.replace("<", "").replace(">", "+").strip("+").upper(), muted=True), False, False, 0)
        row.pack_end(_label("install with: chinchilla shortcuts install", muted=True), False, False, 0)
        shortcut.add(row)
        page.pack_start(shortcut, False, False, 0)

        page.pack_start(
            self._save_row(),
            False,
            False,
            0,
        )

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
            frame = Gtk.Frame(label=action.id)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_start(8)
            box.set_margin_end(8)
            box.set_margin_top(6)
            box.set_margin_bottom(8)

            title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title_entry = _entry(action.title, width=200)
            title_entry.set_max_length(18)
            web_switch = Gtk.Switch()
            web_switch.set_active(action.web_default)
            reset = Gtk.Button(label="Reset to default")
            reset.get_style_context().add_class("ghost-button")
            reset.connect("clicked", self._on_reset_action, action.id, title_entry)
            title_row.pack_start(_label("Title"), False, False, 0)
            title_row.pack_start(title_entry, False, False, 0)
            title_row.pack_end(reset, False, False, 0)
            title_row.pack_end(web_switch, False, False, 0)
            title_row.pack_end(_label("Web by default", muted=True), False, False, 0)
            box.pack_start(title_row, False, False, 0)

            prompt_view = _textview(action.prompt, 96)
            box.pack_start(_scrolled(prompt_view, 96), False, False, 0)
            frame.add(box)
            page.pack_start(frame, False, False, 0)
            self.action_rows[action.id] = (title_entry, prompt_view, web_switch)
        page.pack_start(self._save_row(), False, False, 0)

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
        group = None
        for provider in self.settings.providers.values():
            radio = Gtk.RadioButton.new_with_label_from_widget(
                group, f"{provider.label}  ({provider.id})"
            )
            group = group or radio
            radio.set_active(self.settings.active_provider == provider.id)
            page.pack_start(radio, False, False, 0)

            grid = Gtk.Grid(column_spacing=10, row_spacing=6)
            grid.set_margin_start(24)
            base_url = _entry(provider.base_url or "", width=320)
            model = _entry(provider.model, width=240)
            if provider.id == "custom":
                env_provider = config.provider_from_env("custom")
                base_url.set_placeholder_text(env_provider.base_url or "https://host/v1")
                model.set_placeholder_text(env_provider.model or "model name")
            key_entry = _entry("", password=True, width=320)
            status = _label(f"key: {config.key_source(provider.id)}", muted=True)
            save_key = Gtk.Button(label="Save key")
            save_key.get_style_context().add_class("ghost-button")
            save_key.connect("clicked", self._on_save_key, provider.id, key_entry, status)

            grid.attach(_label("Base URL"), 0, 0, 1, 1)
            grid.attach(base_url, 1, 0, 2, 1)
            grid.attach(_label("Model"), 0, 1, 1, 1)
            grid.attach(model, 1, 1, 2, 1)
            grid.attach(_label("API key"), 0, 2, 1, 1)
            grid.attach(key_entry, 1, 2, 1, 1)
            grid.attach(save_key, 2, 2, 1, 1)
            grid.attach(status, 1, 3, 2, 1)
            page.pack_start(grid, False, False, 0)

            self.provider_widgets[provider.id] = {
                "radio": radio,
                "base_url": base_url,
                "model": model,
                "status": status,
            }
        page.pack_start(self._save_row(), False, False, 0)

    def _build_web(self) -> None:
        page = self._page("Web")
        self.mcp_switch = Gtk.Switch()
        self.mcp_switch.set_active(self.settings.mcp_enabled)
        self.mcp_command_entry = _entry(" ".join(self.settings.mcp_command), width=360)
        self.chrome_entry = _entry(self.settings.mcp_env.get("CHROME_PATH", ""), width=260)
        self.profile_entry = _entry(self.settings.mcp_env.get("GSEARCH_PROFILE", ""), width=260)
        self.probe_label = _label("", muted=True, wrap=True)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        grid.attach(_label("Enable web search"), 0, 0, 1, 1)
        grid.attach(self.mcp_switch, 1, 0, 1, 1)
        grid.attach(_label("MCP command"), 0, 1, 1, 1)
        grid.attach(self.mcp_command_entry, 1, 1, 1, 1)
        grid.attach(_label("CHROME_PATH"), 0, 2, 1, 1)
        grid.attach(self.chrome_entry, 1, 2, 1, 1)
        grid.attach(_label("GSEARCH_PROFILE"), 0, 3, 1, 1)
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
        page.pack_start(self._save_row(), False, False, 0)

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
            row.pack_start(_label(name), False, False, 0)
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

    def _save_row(self) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(10)
        row.pack_end(_label("Saved to settings.json", muted=True), False, False, 0)
        save = Gtk.Button(label="Save")
        save.get_style_context().add_class("accent-button")
        save.connect("clicked", lambda *_: self.save())
        row.pack_end(save, False, False, 0)
        return row

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

    def collect(self) -> config.Settings:
        settings = self.settings
        settings.language = self.language_entry.get_text().strip() or config.DEFAULT_LANGUAGE
        settings.level = self.level_entry.get_text().strip() or config.DEFAULT_LEVEL
        settings.save_sessions = bool(self.save_switch.get_active())
        settings.web_enabled = bool(self.web_default_switch.get_active())
        settings.retention_days = int(self.retention_spin.get_value())

        for action_id, (title_entry, prompt_view, web_switch) in self.action_rows.items():
            action = settings.action(action_id)
            if action is None:
                continue
            action.title = title_entry.get_text().strip() or action.title
            action.prompt = _text_of(prompt_view).strip() or action.prompt
            action.web_default = bool(web_switch.get_active())

        for provider_id, widgets in self.provider_widgets.items():
            provider = settings.providers[provider_id]
            provider.base_url = widgets["base_url"].get_text().strip()
            provider.model = widgets["model"].get_text().strip()
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
        config.save_settings(settings)
        if self.on_save is not None:
            self.on_save(settings)
        return settings


class SettingsWindow(Gtk.Window):
    def __init__(self, settings: config.Settings, on_save: Callable[[config.Settings], None] | None = None) -> None:
        super().__init__(title="Chinchilla settings")
        theme.apply_css()
        self.set_default_size(600, 640)
        self.set_position(Gtk.WindowPosition.CENTER)
        header = Gtk.HeaderBar()
        header.set_title("Settings")
        header.set_show_close_button(True)
        self.set_titlebar(header)
        self.content = SettingsContent(settings, on_save)
        self.add(self.content)
