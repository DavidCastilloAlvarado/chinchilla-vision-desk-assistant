"""Global hotkey through Carbon's ``RegisterEventHotKey``.

macOS has no keybinding daemon to hand a command to, so the running app owns
the shortcut itself. ``RegisterEventHotKey`` needs no Accessibility grant, and
the Quartz GTK main loop already pumps the events it delivers.
"""

from __future__ import annotations

import ctypes
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from .. import log

LOGGER = log.get("hotkey")


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


SIGNATURE = _fourcc("chin")
EVENT_CLASS_KEYBOARD = _fourcc("keyb")
EVENT_HOTKEY_PRESSED = 5
PARAM_DIRECT_OBJECT = _fourcc("----")
TYPE_HOTKEY_ID = _fourcc("hkid")

CMD = 1 << 8
SHIFT = 1 << 9
OPTION = 1 << 11
CONTROL = 1 << 12

MODIFIERS = {
    "control": CONTROL,
    "ctrl": CONTROL,
    "alt": OPTION,
    "option": OPTION,
    "shift": SHIFT,
    "super": CMD,
    "meta": CMD,
    "cmd": CMD,
    "command": CMD,
    # GTK's <Primary> is Command on macOS
    "primary": CMD,
}

# kVK_* virtual key codes of an ANSI keyboard; they name physical keys, so the
# same position fires on any layout.
KEY_CODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06,
    "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E,
    "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
    "6": 0x16, "5": 0x17, "9": 0x19, "7": 0x1A, "8": 0x1C, "0": 0x1D, "o": 0x1F,
    "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28, "n": 0x2D,
    "m": 0x2E, "space": 0x31, "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76,
    "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D,
    "f11": 0x67, "f12": 0x6F,
}

_TOKEN = re.compile(r"<([^>]+)>")


class HotkeyError(RuntimeError):
    """The accelerator cannot be parsed or macOS refused to register it."""


@dataclass(frozen=True)
class Accelerator:
    key_code: int
    modifiers: int

    @property
    def label(self) -> str:
        names = [
            name
            for flag, name in ((CONTROL, "\u2303"), (OPTION, "\u2325"), (SHIFT, "\u21e7"), (CMD, "\u2318"))
            if self.modifiers & flag
        ]
        key = next((name for name, code in KEY_CODES.items() if code == self.key_code), "?")
        return "".join(names) + key.upper()


def parse(accelerator: str) -> Accelerator:
    """Turn a GTK accelerator such as ``<Control><Alt>a`` into Carbon codes."""
    text = (accelerator or "").strip()
    modifiers = 0
    for name in _TOKEN.findall(text):
        flag = MODIFIERS.get(name.strip().lower())
        if flag is None:
            raise HotkeyError(f"unknown modifier <{name}> in {accelerator!r}")
        modifiers |= flag
    key = _TOKEN.sub("", text).strip().lower()
    if key not in KEY_CODES:
        raise HotkeyError(f"unsupported key {key!r} in {accelerator!r}")
    if not modifiers:
        raise HotkeyError(f"{accelerator!r} needs at least one modifier")
    return Accelerator(KEY_CODES[key], modifiers)


class _HotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


@lru_cache(maxsize=1)
def _carbon():
    lib = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    lib.GetApplicationEventTarget.restype = ctypes.c_void_p
    lib.GetApplicationEventTarget.argtypes = []
    lib.InstallEventHandler.restype = ctypes.c_int32
    lib.InstallEventHandler.argtypes = [
        ctypes.c_void_p,
        _HANDLER,
        ctypes.c_ulong,
        ctypes.POINTER(_EventTypeSpec),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.RemoveEventHandler.restype = ctypes.c_int32
    lib.RemoveEventHandler.argtypes = [ctypes.c_void_p]
    lib.RegisterEventHotKey.restype = ctypes.c_int32
    lib.RegisterEventHotKey.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        _HotKeyID,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    lib.UnregisterEventHotKey.restype = ctypes.c_int32
    lib.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
    lib.GetEventParameter.restype = ctypes.c_int32
    lib.GetEventParameter.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    return lib


class GlobalHotkey:
    """One registered shortcut that calls ``callback`` on the main thread."""

    _next_id = 1

    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.accelerator: str = ""
        self._id = GlobalHotkey._next_id
        GlobalHotkey._next_id += 1
        self._handler_ref = ctypes.c_void_p()
        self._hotkey_ref = ctypes.c_void_p()
        # keep the C callable alive as long as the handler is installed
        self._proc = _HANDLER(self._on_event)

    @property
    def registered(self) -> bool:
        return bool(self._hotkey_ref.value)

    def _on_event(self, _call_ref, event, _user_data) -> int:
        hotkey = _HotKeyID()
        status = _carbon().GetEventParameter(
            event,
            PARAM_DIRECT_OBJECT,
            TYPE_HOTKEY_ID,
            None,
            ctypes.sizeof(hotkey),
            None,
            ctypes.byref(hotkey),
        )
        if status == 0 and hotkey.signature == SIGNATURE and hotkey.id == self._id:
            LOGGER.info("hotkey %s pressed", self.accelerator)
            try:
                self.callback()
            except Exception:  # pragma: no cover - never unwind into Carbon
                LOGGER.exception("hotkey callback failed")
        return 0

    def register(self, accelerator: str) -> Accelerator:
        parsed = parse(accelerator)
        self.unregister()
        lib = _carbon()
        target = lib.GetApplicationEventTarget()
        if not self._handler_ref.value:
            spec = _EventTypeSpec(EVENT_CLASS_KEYBOARD, EVENT_HOTKEY_PRESSED)
            status = lib.InstallEventHandler(
                target, self._proc, 1, ctypes.byref(spec), None, ctypes.byref(self._handler_ref)
            )
            if status != 0:
                raise HotkeyError(f"InstallEventHandler failed ({status})")
        status = lib.RegisterEventHotKey(
            parsed.key_code,
            parsed.modifiers,
            _HotKeyID(SIGNATURE, self._id),
            target,
            0,
            ctypes.byref(self._hotkey_ref),
        )
        if status != 0:
            self._hotkey_ref = ctypes.c_void_p()
            raise HotkeyError(
                f"macOS refused {parsed.label} ({status}); another app may already own it"
            )
        self.accelerator = accelerator
        LOGGER.info("hotkey %s registered (%s)", accelerator, parsed.label)
        return parsed

    def unregister(self) -> None:
        if self._hotkey_ref.value:
            _carbon().UnregisterEventHotKey(self._hotkey_ref)
            self._hotkey_ref = ctypes.c_void_p()
        self.accelerator = ""

    def close(self) -> None:
        self.unregister()
        if self._handler_ref.value:
            _carbon().RemoveEventHandler(self._handler_ref)
            self._handler_ref = ctypes.c_void_p()
