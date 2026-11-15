"""Application wiring: shortcut, capture, overlay, panel and agent."""

from __future__ import annotations

import queue
import threading
from typing import Callable


from .. import log, paths, shortcuts
from ..core import capture as capture_module
from ..core import permission
from ..core.agent import Agent, AgentEvent
from ..core.thread import Turn, Usage
from ..store import config, session as session_store
from . import panel as panel_ui
from . import theme, tray as tray_ui
from .gtk import Gdk, GLib, Gtk

LOGGER = log.get("app")
APP_ID = "io.github.chinchilla.App"
PUMP_MS = 60
CAPTURE_DELAY_MS = 220
_DONE = AgentEvent("done")


def quick_action_labels(settings: config.Settings) -> list[tuple[str, str]]:
    return [(action.id, action.title) for action in settings.actions]


class App(Gtk.Application):
    """Single instance application driven by the global shortcut."""

    def __init__(
        self,
        settings: config.Settings | None = None,
        capture_on_activate: bool = True,
        agent_factory: Callable[[session_store.Session, config.Settings], Agent] | None = None,
    ) -> None:
        super().__init__(application_id=APP_ID, flags=0)
        theme.apply_css()
        self.settings = settings or config.load_settings()
        self.capture_on_activate = capture_on_activate
        self.agent_factory = agent_factory or Agent
        self.session = session_store.create_session(self.settings)
        self.tray: tray_ui.TrayIcon | None = None
        self.window: panel_ui.PanelWindow | None = None
        self.sessions_popover = None
        self.settings_window = None
        self.overlay = None
        self.agent: Agent | None = None
        self.events: queue.Queue[AgentEvent] = queue.Queue()
        self.busy = False
        self._stop = threading.Event()
        self.status = ""
        self.capture_parent = ""

    # ------------------------------------------------------------ application

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.hold()  # the panel hides instead of closing, so keep the process alive
        self.build_ui()

    def build_ui(self) -> None:
        paths.ensure_dirs()
        self._build_window()
        self._install_tray()

    def do_activate(self) -> None:
        self.refresh_config()
        if not self.capture_on_activate:
            # the daemon starts without capturing, later activations do capture
            self.capture_on_activate = True
            return
        self.start_capture()

    def _build_window(self) -> None:
        self.window = panel_ui.PanelWindow(
            actions=quick_action_labels(self.settings),
            on_prompt=self._on_action,
            on_capture=self.start_capture,
            on_new_session=self.new_session,
            on_sessions=self.toggle_sessions,
            on_settings=self.open_settings,
            on_web=self.set_web,
            on_send=self._on_send,
            on_close=self.hide_panel,
            on_retry=self.retry_last,
            on_stop=self.stop_turn,
        )
        self.window.connect("destroy", lambda *_: self.quit())
        self.refresh_panel()

    def _install_tray(self) -> None:
        self.tray = tray_ui.TrayIcon(
            on_capture=self.start_capture,
            on_sessions=self.toggle_sessions,
            on_settings=self.open_settings,
            on_quit=self.quit_app,
        )
        if not self.tray.install():
            LOGGER.info("no tray icon available; use the shortcut or the CLI")

    # --------------------------------------------------------------- sessions

    def new_session(self) -> None:
        self.session = session_store.create_session(self.settings)
        self.refresh_panel()
        self.show_panel()
        self._status("new session")

    def open_session(self, session_id: str) -> None:
        loaded = session_store.Session.load(session_id)
        if loaded is None:
            self._status("session not found", "error")
            return
        self.session = loaded
        self.refresh_panel()
        self.show_panel()

    def _make_agent(self) -> Agent:
        return self.agent_factory(self.session, self.settings)

    def refresh_config(self) -> bool:
        """Re-read settings and the environment before serving an activation.

        Ctrl+Alt+A activates this same process again (`Gtk.Application` is a
        single instance and the app holds it open), so a key or endpoint edited
        on disk would otherwise only apply after a logout.
        """
        if self.settings_window is not None:
            return False
        fresh = config.load_settings()
        changed = fresh.to_dict() != self.settings.to_dict()
        if changed:
            self.settings = fresh
            LOGGER.info("settings reloaded from disk")
        self.agent = None
        self._sync_provider_label()
        return changed

    def _sync_provider_label(self) -> None:
        """Show the live provider, its model and the endpoint behind the tooltip."""
        if self.window is None:
            return
        label = self.window.content.provider_label
        label.set_text(self.settings.provider_label())
        provider = config.resolved_provider(self.settings)
        label.set_tooltip_text(
            f"{provider.base_url or 'no endpoint'} ({config.key_source(provider.id)})"
        )

    def refresh_panel(self) -> None:
        if self.window is None:
            return
        self.window.content.set_session(
            title=self.session.title,
            turns=self.session.turns,
            captures=self.session.captures,
            provider_label=self.settings.provider_label(),
            web_enabled=self.session.web_enabled,
        )
        self._sync_provider_label()

    def toggle_sessions(self) -> None:
        from .sessions import SessionsPopover

        if self.window is None:
            return
        if self.sessions_popover is None:
            self.sessions_popover = SessionsPopover(
                on_pick=self.open_session,
                on_new=self.new_session,
                active_id=self.session.id,
            )
            self.sessions_popover.set_relative_to(self.window.content.title_button)
        self.sessions_popover.pane.set_active(self.session.id)
        self.sessions_popover.pane.reload()
        self.sessions_popover.popup()

    # ---------------------------------------------------------------- capture

    def start_capture(self) -> None:
        if self.busy:
            self.show_panel()
            self._status("wait for the current answer", "error")
            return
        # The panel would end up in the frozen frame, so it steps aside while
        # the region is picked.
        self.hide_panel()
        self.status = ""
        GLib.timeout_add(CAPTURE_DELAY_MS, self._spawn_capture_worker)

    def _spawn_capture_worker(self) -> bool:
        self.capture_parent = self.panel_handle()
        LOGGER.info("capture start handle=%r", self.capture_parent)
        threading.Thread(target=self._capture_worker, daemon=True).start()
        return False

    def _capture_worker(self) -> None:
        allowed, detail = permission.ensure()
        if not allowed:
            LOGGER.warning("silent capture unavailable: %s", detail)
            GLib.idle_add(self._run_area_selector, detail)
            return
        try:
            grab = capture_module.grab_screen(parent=self.capture_parent)
        except capture_module.CaptureError as exc:
            LOGGER.warning("screen grab failed: %s", exc)
            GLib.idle_add(self._run_area_selector, str(exc))
            return
        LOGGER.info("silent grab %sx%s via %s", grab.image.width, grab.image.height, grab.backend)
        GLib.idle_add(self._run_overlay, grab.image)

    def panel_handle(self) -> str:
        if self.window is None:
            return ""
        return self.window.parent_handle()

    def _run_area_selector(self, reason: str = "") -> bool:
        """Fallback: let the desktop draw its own selector, like macOS does."""
        self.show_panel()
        if reason:
            LOGGER.info("area selector fallback: %s", reason)
        self._status("drag the area to capture in the GNOME selector")
        threading.Thread(target=self._area_worker, daemon=True).start()
        return False

    def _area_worker(self) -> None:
        try:
            grab = capture_module.grab_area()
        except capture_module.CaptureError as exc:
            GLib.idle_add(self._status, f"capture failed: {exc}", "error")
            GLib.idle_add(self.show_panel)
            return
        LOGGER.info("area selector returned %sx%s", grab.image.width, grab.image.height)
        GLib.idle_add(self.add_capture, grab.image)

    def _run_overlay(self, image) -> bool:
        from .overlay import run_overlay

        rect = run_overlay(background=image)
        if rect is None:
            self._status("capture cancelled")
            self.show_panel()
            return False
        try:
            cropped = capture_module.crop(image, rect, (image.width, image.height))
        except Exception as exc:
            self._status(f"cannot crop: {exc}", "error")
            self.show_panel()
            return False
        self.add_capture(cropped, rect)
        return False

    def add_capture(self, image, rect=None) -> None:
        capture = self.session.add_capture(image)
        if rect is not None:
            capture.rect = rect.to_dict()
            self.session.save()
        self.window.content.set_captures(self.session.captures)
        self._status(f"cut added ({image.width}x{image.height})")
        self.show_panel()

    # ------------------------------------------------------------------ turns

    def _on_action(self, action_id: str, _label: str | None = None) -> None:
        prompt = self._make_agent().action_prompt(action_id)
        self.submit(prompt, action_id)

    def _on_send(self, text: str) -> None:
        self.submit(text, None)

    def submit(self, text: str, action_id: str | None = None) -> None:
        text = (text or "").strip()
        if not text or self.busy or self.window is None:
            return
        pending = self.session.pending_captures()
        if action_id and not pending:
            self._status("take a cut first: Ctrl+Alt+A", "error")
            return

        turn = Turn(
            role="user",
            text=text,
            captures=[item.id for item in pending],
            action=action_id,
        )
        if pending:
            self.session.mark_sent(turn.captures)
            self.session.save()
        self.window.content.set_captures(self.session.captures)
        if action_id and self.session.title == session_store.DEFAULT_TITLE:
            action = self.settings.action(action_id)
            self.session.title = action.title if action is not None else self.session.title
        self.window.content.add_turn(turn)
        self._start_stream(turn)

    def _start_stream(self, turn: Turn) -> None:
        """Run the agent for a turn that is already part of the session."""
        self.busy = True
        content = self.window.content
        content.set_active_action(turn.action)
        content.start_assistant_turn(turn.action)
        content.set_busy(True)
        self._status("thinking")

        agent = self._make_agent()
        self.agent = agent
        self.events = queue.Queue()
        self._stop.clear()

        def worker() -> None:
            try:
                for event in agent.run(turn):
                    if self._stop.is_set():
                        break
                    self.events.put(event)
            except Exception as exc:  # pragma: no cover - provider blow ups
                LOGGER.exception("agent failed")
                self.events.put(AgentEvent("error", text=str(exc)))
            finally:
                self.events.put(_DONE)

        threading.Thread(target=worker, daemon=True).start()
        GLib.timeout_add(PUMP_MS, self._pump)

    def stop_turn(self) -> None:
        """Keep what arrived so far and stop paying for the rest of the stream."""
        if not self.busy:
            return
        self._stop.set()
        self._finish_turn("stopped")

    def retry_last(self) -> None:
        """Regenerate the last answer; the question is not sent twice."""
        if self.busy:
            return
        ask = next(
            (turn for turn in reversed(self.session.turns) if turn.role == "user"), None
        )
        if ask is None or not ask.text:
            self._status("nothing to retry", "error")
            return
        index = next(
            i
            for i in range(len(self.session.turns) - 1, -1, -1)
            if self.session.turns[i] is ask
        )
        del self.session.turns[index + 1 :]
        self.session.save()
        self.refresh_panel()
        self._start_stream(ask)

    def _pump(self) -> bool:
        finished = False
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event is _DONE:
                finished = True
                continue
            self._handle(event)
        if finished:
            self._finish_turn()
            return False
        return True

    def _handle(self, event: AgentEvent) -> None:
        content = self.window.content if self.window else None
        if content is None:
            return
        if event.type == "text":
            content.append_text(event.text)
        elif event.type == "tool":
            self._status(f"searching: {event.detail or event.tool}")
        elif event.type == "notice":
            self._status(event.text)
        elif event.type == "sources":
            content.finish_assistant_turn(sources=event.sources)
        elif event.type == "error":
            content.finish_assistant_turn(error=event.text)

    def _finish_turn(self, status: str = "ready") -> None:
        self.busy = False
        if self.window is not None:
            self.window.content.finish_assistant_turn()
            self.window.content.set_busy(False)
            self.window.content.set_title(self.session.title)
            self.window.content.set_usage(Usage.total(self.session.turns))
        self._status(status)

    # ------------------------------------------------------------- ui helpers

    def set_web(self, enabled: bool) -> None:
        self.session.web_enabled = bool(enabled)
        self.session.save()
        self._status("web search on" if enabled else "web search off")

    def _status(self, text: str, kind: str = "info") -> None:
        self.status = text
        if self.window is not None:
            self.window.content.set_status(text, kind)

    def show_panel(self) -> None:
        if self.window is None:
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geometry = monitor.get_geometry()
        if not self.window.get_visible():
            self.window.show_at(geometry.width, geometry.height)
        else:
            self.window.present_with_time(Gdk.CURRENT_TIME)

    def hide_panel(self) -> None:
        if self.window is not None:
            self.window.hide()

    def open_settings(self) -> None:
        from .settings import SettingsWindow

        if self.settings_window is None:
            self.settings_window = SettingsWindow(self.settings, on_save=self._apply_settings)
            self.settings_window.connect("destroy", self._forget_settings_window)
        self.settings_window.show_all()
        self.settings_window.present()

    def _forget_settings_window(self, *_args) -> None:
        self.settings_window = None

    def _apply_settings(self, settings: config.Settings) -> None:
        self.settings = settings
        self._sync_provider_label()
        self.agent = None
        self._status("settings saved")

    def shutdown(self) -> None:
        if self.tray is not None:
            self.tray.remove()
            self.tray = None
        if self.window is not None:
            self.window.destroy()
            self.window = None

    def quit_app(self) -> None:
        self.shutdown()
        if self.get_is_registered():
            self.release()
            self.quit()


def run_app(argv: list[str] | None = None, capture: bool = True) -> int:
    from ..runtime import ensure_gdk_backend

    ensure_gdk_backend()
    app = App(capture_on_activate=capture)
    return app.run([*(argv or [])])


def shortcut_status() -> str:
    return shortcuts.status().summary