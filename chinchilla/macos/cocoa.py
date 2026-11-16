"""Small Objective-C bridge for the window calls GTK Quartz does not expose.

Every function is best effort: it returns False instead of raising, because a
missing native call only costs polish (focus, stacking), never the capture.
All of them must run on the main thread, like any AppKit call.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from functools import lru_cache

from .. import log

LOGGER = log.get("macos")

# NSApplicationActivationPolicyAccessory: no Dock icon, no menu bar, still able
# to own windows and take the keyboard focus.
POLICY_ACCESSORY = 1
# Above the menu bar and the Dock, like the system screenshot selector.
LEVEL_SCREEN_SAVER = 1000
LEVEL_FLOATING = 3
# canJoinAllSpaces | fullScreenAuxiliary: the overlay also shows over an app in
# full screen and on whatever Space is active.
BEHAVIOR_ALL_SPACES = (1 << 0) | (1 << 8)


@lru_cache(maxsize=1)
def _objc():
    lib = ctypes.CDLL(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
    lib.objc_getClass.restype = ctypes.c_void_p
    lib.objc_getClass.argtypes = [ctypes.c_char_p]
    lib.sel_registerName.restype = ctypes.c_void_p
    lib.sel_registerName.argtypes = [ctypes.c_char_p]
    # AppKit has to be loaded for NSApplication to exist in a plain python
    ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
    return lib


def _send(receiver: int | None, selector: str, *args, restype=ctypes.c_void_p, argtypes=()):
    """`objc_msgSend` with an explicit signature (arm64 has no varargs ABI)."""
    lib = _objc()
    address = ctypes.cast(lib.objc_msgSend, ctypes.c_void_p).value
    function = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(address)
    return function(receiver, lib.sel_registerName(selector.encode()), *args)


def _ns_app() -> int | None:
    cls = _objc().objc_getClass(b"NSApplication")
    return _send(cls, "sharedApplication") if cls else None


@lru_cache(maxsize=1)
def _gdk_library():
    """The libgdk-3 image PyGObject already loaded into this process."""
    system = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    system._dyld_image_count.restype = ctypes.c_uint32
    system._dyld_get_image_name.restype = ctypes.c_char_p
    system._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    for index in range(system._dyld_image_count()):
        name = system._dyld_get_image_name(index) or b""
        if b"libgdk-3" in name:
            lib = ctypes.CDLL(name.decode())
            lib.gdk_quartz_window_get_nswindow.restype = ctypes.c_void_p
            lib.gdk_quartz_window_get_nswindow.argtypes = [ctypes.c_void_p]
            return lib
    raise OSError("libgdk-3 is not loaded")


def _gobject_pointer(obj) -> int:
    capsule = obj.__gpointer__
    get = ctypes.pythonapi.PyCapsule_GetPointer
    get.restype = ctypes.c_void_p
    get.argtypes = [ctypes.py_object, ctypes.c_char_p]
    return get(capsule, None)


def ns_window(gtk_window) -> int | None:
    """The NSWindow behind a realized Gtk.Window."""
    gdk_window = gtk_window.get_window()
    if gdk_window is None:
        return None
    return _gdk_library().gdk_quartz_window_get_nswindow(_gobject_pointer(gdk_window)) or None


def set_accessory() -> bool:
    """Run like a menu bar utility: no Dock icon, no app menu."""
    try:
        app = _ns_app()
        _send(app, "setActivationPolicy:", POLICY_ACCESSORY, restype=ctypes.c_bool, argtypes=[ctypes.c_long])
        return True
    except Exception as exc:  # pragma: no cover - depends on AppKit
        LOGGER.warning("cannot set the activation policy: %s", exc)
        return False


def activate() -> bool:
    """Take the keyboard focus away from the app that was in front.

    The hotkey fires while another app is active; GTK raises its window but
    does not activate the process, so without this the keys keep going to the
    other app.
    """
    try:
        app = _ns_app()
        _send(app, "activateIgnoringOtherApps:", True, restype=None, argtypes=[ctypes.c_bool])
        return True
    except Exception as exc:  # pragma: no cover - depends on AppKit
        LOGGER.warning("cannot activate the app: %s", exc)
        return False


def yield_focus() -> bool:
    """Hand the focus back to the previous app once our windows are gone."""
    try:
        app = _ns_app()
        _send(app, "hide:", None, restype=None, argtypes=[ctypes.c_void_p])
        return True
    except Exception as exc:  # pragma: no cover - depends on AppKit
        LOGGER.warning("cannot hide the app: %s", exc)
        return False


def keep_visible(gtk_window, level: int = LEVEL_FLOATING) -> bool:
    """Float over other apps and stay put when they take the focus.

    GTK maps the utility type hint to an NSWindow that hides on deactivate,
    so the panel vanished at the first click elsewhere, and its keep-above
    request does not reach AppKit.
    """
    try:
        window = ns_window(gtk_window)
        if not window:
            return False
        _send(window, "setHidesOnDeactivate:", False, restype=None, argtypes=[ctypes.c_bool])
        _send(window, "setLevel:", level, restype=None, argtypes=[ctypes.c_long])
        return True
    except Exception as exc:  # pragma: no cover - depends on AppKit
        LOGGER.warning("cannot pin the window: %s", exc)
        return False


def raise_window(gtk_window, level: int, all_spaces: bool = False) -> bool:
    """Put a realized window on an AppKit level GTK has no type hint for."""
    try:
        window = ns_window(gtk_window)
        if not window:
            return False
        _send(window, "setLevel:", level, restype=None, argtypes=[ctypes.c_long])
        if all_spaces:
            _send(
                window,
                "setCollectionBehavior:",
                BEHAVIOR_ALL_SPACES,
                restype=None,
                argtypes=[ctypes.c_ulong],
            )
        _send(window, "makeKeyAndOrderFront:", None, restype=None, argtypes=[ctypes.c_void_p])
        return True
    except Exception as exc:  # pragma: no cover - depends on AppKit
        LOGGER.warning("cannot raise the window: %s", exc)
        return False
