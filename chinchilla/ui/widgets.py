"""Small widget helpers shared by the panel and the settings dialog."""

from __future__ import annotations

from .gtk import Gtk


def place_knob(track: Gtk.Box, knob: Gtk.Widget, at_end: bool) -> None:
    """Pack the knob against the side of the track that matches the state.

    ``halign`` cannot move a child inside a ``Gtk.Box`` cell, so the knob is
    re-packed at the requested end instead.
    """
    if knob.get_parent() is not None:
        track.remove(knob)
    if at_end:
        track.pack_end(knob, False, False, 0)
    else:
        track.pack_start(knob, False, False, 0)
    knob.show()