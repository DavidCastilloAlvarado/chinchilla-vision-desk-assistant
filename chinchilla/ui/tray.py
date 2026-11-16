"""Tray icon: AppIndicator when the desktop has it, StatusIcon otherwise."""

from __future__ import annotations

from typing import Callable

from .. import system
from . import theme
from .gtk import GdkPixbuf, GLib, Gtk

APP_ID = "chinchilla"
ICON_NAME = "edit-find-symbolic"
MENU_BAR_ICON_SIZE = 44  # drawn at 2x, macOS shows it at 22 points
MENU_DELAY_MS = 120
_RETIRED_ICONS: list = []


def menu_bar_pixbuf(size: int = MENU_BAR_ICON_SIZE) -> GdkPixbuf.Pixbuf:
    """A magnifier in the accent colour, drawn here so no icon theme is needed.

    Homebrew's GTK ships without an icon theme, and the usual one
    (adwaita-icon-theme) drags a whole Rust toolchain in through librsvg.
    """
    from PIL import Image, ImageDraw

    scale = 4
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = tuple(int(channel * 255) for channel in theme.ACCENT) + (255,)
    width = int(big * 0.11)
    lens = (int(big * 0.12), int(big * 0.12), int(big * 0.66), int(big * 0.66))
    draw.ellipse(lens, outline=color, width=width)
    draw.line(
        (int(big * 0.60), int(big * 0.60), int(big * 0.88), int(big * 0.88)),
        fill=color,
        width=int(width * 1.3),
    )
    image = image.resize((size, size), Image.LANCZOS)
    data = GLib.Bytes.new(image.tobytes())
    return GdkPixbuf.Pixbuf.new_from_bytes(
        data, GdkPixbuf.Colorspace.RGB, True, 8, size, size, size * 4
    )


def _menu(entries: list[tuple[str, Callable[[], None]]]) -> Gtk.Menu:
    menu = Gtk.Menu()
    for label, callback in entries:
        if label == "Quit" and menu.get_children():
            menu.append(Gtk.SeparatorMenuItem())
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
        self._menu = None

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
        if system.is_mac():
            return False
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
            if system.is_mac():
                # a menu bar item opens its menu on a plain click
                icon = Gtk.StatusIcon.new_from_pixbuf(menu_bar_pixbuf())
                icon.connect(
                    "activate",
                    lambda status_icon: GLib.timeout_add(
                        MENU_DELAY_MS, self._popup_after_click, status_icon
                    ),
                )
            else:
                icon = Gtk.StatusIcon.new_from_icon_name(ICON_NAME)
                icon.connect("activate", lambda *_args: self.on_capture())
            icon.set_tooltip_text("Chinchilla")
            icon.connect("popup-menu", self._on_popup)
            icon.set_visible(True)
        except Exception:
            return False
        self._status_icon = icon
        return True

    def _popup_after_click(self, icon: Gtk.StatusIcon) -> bool:
        """Open the menu once the click is over, as a non-button popup.

        Quartz emits `activate` on the press; a menu opened right then under
        the pointer took the release as a pick, and a quick click could land
        on Quit.
        """
        self._on_popup(icon, 0, 0)
        return False

    def _on_popup(self, icon: Gtk.StatusIcon, button: int, activate_time: int) -> None:
        # keep a reference: a menu collected while it is open closes at once
        self._menu = _menu(self.entries())
        self._menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    def remove(self) -> None:
        if self._status_icon is not None:
            self._status_icon.set_visible(False)
            if system.is_mac():
                # finalizing a Quartz status icon crashes GTK a few cycles
                # later; a hidden one costs nothing until the process exits
                _RETIRED_ICONS.append(self._status_icon)
            self._status_icon = None
        if self._indicator is not None:
            self._indicator = None
        self.kind = "none"