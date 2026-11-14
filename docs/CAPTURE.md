# Capture backends

Wayland does not let an application read the screen directly, so Chinchilla
tries a chain of backends and uses the first one that returns pixels.
`chinchilla doctor -v` prints the state of every backend.

| Backend | Kind | Notes |
| --- | --- | --- |
| `file` | screen | Uses `CHINCHILLA_CAPTURE_SOURCE`; for tests and demos |
| `portal` | screen | `org.freedesktop.portal.Screenshot`, non interactive |
| `portal-area` | area | The same portal with the desktop's own area selector |
| `gnome-shell` | screen | `org.gnome.Shell.Screenshot` (may be restricted) |
| `grim` | screen | wlroots compositors |
| `gnome-screenshot` | screen | GNOME helper, bypasses the portal |
| `spectacle` | screen | KDE |
| `scrot` | screen | X11 |
| `import` | screen | ImageMagick, X11 |
| `x11` | screen | `PIL.ImageGrab`, X11 sessions only |

## The permission prompt

On GNOME 46 a non interactive portal request must be sent with `modal: true`,
otherwise the portal answers `cancelled` immediately. The first request shows a
dialog asking permission to take a screenshot; once allowed it stops asking.
If no dialog appears, install one of the command line backends, for example
`sudo apt install gnome-screenshot`, and Chinchilla will use it automatically.

## Modes

- **Frozen frame** (preferred): a screen backend returns the whole screen, the
  overlay draws it dimmed, and the crop happens in process.
- **Desktop selector** (fallback): only an area backend is available, so the
  desktop's own selector picks the region and Chinchilla receives a crop.
