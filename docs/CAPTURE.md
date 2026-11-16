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

On macOS the chain is replaced by the system tool (the Linux backends are not
even probed there):

| Backend | Kind | Notes |
| --- | --- | --- |
| `file` | screen | Same as on Linux |
| `screencapture` | screen | `screencapture -x -m`: main display, no shutter sound |
| `screencapture-area` | area | `screencapture -x -i`: the system crosshair; `Esc` leaves no file and reads as "capture cancelled" |
| `clipboard` | area | the user's own ⌘⌃⇧4 cut (or plain ⌘⇧4 when screenshots are set to *Save to › Clipboard*), read from the pasteboard; the only path without Screen Recording. The panel takes every new image while it is open; the CLI waits up to 90 s for one |

Both need the **Screen Recording** grant of the responsible app (the terminal,
or Python under the login agent). Without it macOS still returns an image, but
with every window blanked (and `screencapture -i` fails outright), so
Chinchilla checks the grant with `CGPreflightScreenCaptureAccess` first. Without
it the hotkey goes straight to the `clipboard` hand-off: macOS's own screenshot
tool is not bound by the grant, which is what makes Chinchilla usable on a
managed Mac where only an admin can grant Screen Recording.

A user cancel (`Esc` in a selector, `cancelled` from the portal) raises
`CaptureCancelled` and stops the chain instead of falling through to the next
area backend.

## The permission prompt

On GNOME 46 a non interactive portal request must be sent with `modal: true`,
otherwise the portal answers `cancelled` immediately. The first request shows a
dialog asking permission to take a screenshot; once allowed it stops asking.
If no dialog appears, install one of the command line backends, for example
`sudo apt install gnome-screenshot`, and Chinchilla will use it automatically.

On macOS there is no portal: the grant lives in System Settings › Privacy &
Security › Screen & System Audio Recording, and `chinchilla permission grant`
shows the system prompt the first time.

## Modes

- **Frozen frame** (preferred): a screen backend returns the whole screen, the
  overlay draws it dimmed, and the crop happens in process. The overlay reports
  the selection in screen points and the frame is in pixels, so the crop scales
  between both (a Retina or 200 % display keeps its full resolution).
- **Desktop selector** (fallback): only an area backend is available, so the
  desktop's own selector picks the region and Chinchilla receives a crop.
