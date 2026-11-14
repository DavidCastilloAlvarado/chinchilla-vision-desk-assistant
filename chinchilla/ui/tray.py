"""Tray icon: AppIndicator when the desktop has it, StatusIcon otherwise."""

from __future__ import annotations

from typing import Callable

from . import theme
from .gtk import Gtk

APP_ID = "chinchilla"
ICON_NAME = "edit-find-symbolic"


def _menu(entries: list[tuple[str, Callable[[], None]]]) -> Gtk.Menu:
    menu = Gtk.Menu()
    for label, callback in entries:
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda _item, cb=callback: cb())
        menu.append(item)
    menu.show_all()
    return menu


class TrayIcon:
    """Best-effort status icon.

    GNOME 46 hides `Gtk.StatusIcon` behind an extension and only shows
    indicators through the AppIndicator protocol, so that is tried first and
    the caller keeps working when neither is present.
    """

    def __init__(
        self,
        on_capture: Callable[[], None],
        on_sessions: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self.on_capture = on_capture
        self.on_sessions = on_sessions
        self.on_settings = on_settings
        self.on_quit = on_quit
        self.kind = "none"
        self._indicator = None
        self._status_icon = None

    def entries(self) -> list[tuple[str, Callable[[], None]]]:
        entries: list[tuple[str, Callable[[], None]]] = [("Capture region", self.on_capture)]
        if self.on_sessions is not None:
            entries.append(("Sessions", self.on_sessions))
        if self.on_settings is not None:
            entries.append(("Settings", self.on_settings))
        if self.on_quit is not None:
            entries.append(("Quit", self.on_quit))
        return entries

    def install(self) -> bool:
        theme.apply_css()
        if self._install_indicator():
            self.kind = "appindicator"
            return True
        if self._install_status_icon():
            self.kind = "status-icon"
            return True
        return False

    def _install_indicator(self) -> bool:
        try:
            import gi

            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as AppIndicator  # type: ignore
        except (ImportError, ValueError):
            try:
                import gi

                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3 as AppIndicator  # type: ignore
            except (ImportError, ValueError):
                return False
        try:
            indicator = AppIndicator.Indicator.new(
                APP_ID, ICON_NAME, AppIndicator.IndicatorCategory.APPLICATION_STATUS
            )
            indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
            indicator.set_menu(_menu(self.entries()))
        except Exception:
            return False
        self._indicator = indicator
        return True

    def _install_status_icon(self) -> bool:
        if not hasattr(Gtk, "StatusIcon"):
            return False
        try:
            icon = Gtk.StatusIcon.new_from_icon_name(ICON_NAME)
            icon.set_tooltip_text("Chinchilla")
            icon.connect("activate", lambda *_args: self.on_capture())
            icon.connect("popup-menu", self._on_popup)
            icon.set_visible(True)
        except Exception:
            return False
        self._status_icon = icon
        return True

    def _on_popup(self, icon: Gtk.StatusIcon, button: int, activate_time: int) -> None:
        menu = _menu(self.entries())
        menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    def remove(self) -> None:
        if self._status_icon is not None:
            self._status_icon.set_visible(False)
            self._status_icon = None
        if self._indicator is not None:
            self._indicator = None
        self.kind = "none"