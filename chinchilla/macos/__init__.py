"""macOS integration done with ctypes, so no extra Python package is needed.

Homebrew's GTK runs on the Quartz backend, which already drives an
``NSApplication``. These modules only reach the few native calls GTK does not
expose: the global hotkey, the Screen Recording grant, window levels, the
login agent, and bringing the app to the front.
"""
