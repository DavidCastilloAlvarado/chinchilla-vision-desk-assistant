"""Sign-in dialog for GitHub Copilot: show the code, wait for the browser."""

from __future__ import annotations

import threading
from typing import Callable

from ..core import copilot
from .gtk import GLib, Gtk


class CopilotLoginDialog(Gtk.Dialog):
    """Device-flow sign-in.

    The worker thread only talks to GitHub; every widget change goes back to the
    main loop through `GLib.idle_add`, because GTK is not thread safe.
    """

    def __init__(
        self,
        parent: Gtk.Window | None = None,
        login: Callable[..., copilot.Credentials] | None = None,
    ) -> None:
        super().__init__(title="Sign in to GitHub Copilot", transient_for=parent, modal=True)
        self.set_default_size(420, 240)
        self.set_resizable(False)
        self.credentials: copilot.Credentials | None = None
        self.error = ""
        self.login = login or copilot.login
        self._started = False

        box = self.get_content_area()
        box.set_spacing(10)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.set_margin_top(14)
        box.set_margin_bottom(6)

        box.add(self._head("1. Open this page"))
        self.page_label = Gtk.Label()
        self.page_label.set_xalign(0)
        self.page_label.set_selectable(True)
        self.page_label.set_text("https://github.com/login/device")
        self.page_label.get_style_context().add_class("copilot-link")
        box.add(self.page_label)

        self.open_button = Gtk.Button(label="Open the browser")
        self.open_button.set_relief(Gtk.ReliefStyle.NONE)
        self.open_button.get_style_context().add_class("ghost-button")
        self.open_button.connect("clicked", lambda *_: self._open_page())
        open_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        open_row.pack_start(self.open_button, False, False, 0)
        box.add(open_row)

        box.add(self._head("2. Enter this code"))
        self.code_label = Gtk.Label(label="\u2026")
        self.code_label.set_xalign(0)
        self.code_label.set_selectable(True)
        self.code_label.get_style_context().add_class("copilot-code")
        box.add(self.code_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.copy_button = Gtk.Button(label="Copy code")
        self.copy_button.set_relief(Gtk.ReliefStyle.NONE)
        self.copy_button.get_style_context().add_class("ghost-button")
        self.copy_button.connect("clicked", lambda *_: self._copy_code())
        row.pack_start(self.copy_button, False, False, 0)
        self.status_label = Gtk.Label(label="starting the login\u2026")
        self.status_label.set_xalign(0)
        self.status_label.set_line_wrap(True)
        self.status_label.get_style_context().add_class("muted-label")
        row.pack_start(self.status_label, True, True, 0)
        box.add(row)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        box.show_all()

    # ------------------------------------------------------------------ pieces

    def _head(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        label.get_style_context().add_class("set-lbl")
        return label

    def _open_page(self) -> None:
        window = self.get_transient_for()
        try:
            Gtk.show_uri_on_window(window, copilot.DEVICE_CODE_URL.replace("/code", "/device"), 0)
        except GLib.Error:
            pass

    def _copy_code(self) -> None:
        clipboard = Gtk.Clipboard.get_default(self.get_display())
        clipboard.set_text(self.code_label.get_text(), -1)
        clipboard.store()

    # ------------------------------------------------------------------- flow

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._worker, daemon=True).start()

    def run(self) -> int:
        """Start the device flow and block until the login finishes or is cancelled."""
        self.start()
        return super().run()

    def _worker(self) -> None:
        try:
            credentials = self.login(on_code=lambda device: GLib.idle_add(self._show_code, device))
        except Exception as exc:  # every failure is shown in the dialog
            GLib.idle_add(self._failed, str(exc))
            return
        GLib.idle_add(self._succeeded, credentials)

    def _show_code(self, device: copilot.DeviceCode) -> bool:
        self.code_label.set_text(device.user_code)
        self.page_label.set_text(device.verification_uri)
        self.status_label.set_text("waiting for the approval in the browser\u2026")
        return False

    def _failed(self, message: str) -> bool:
        self.error = message
        self.status_label.set_text(message)
        context = self.status_label.get_style_context()
        context.remove_class("muted-label")
        context.add_class("error-text")
        return False

    def _succeeded(self, credentials: copilot.Credentials) -> bool:
        self.credentials = credentials
        self.status_label.set_text("signed in, closing\u2026")
        self.response(Gtk.ResponseType.OK)
        return False