import os

import pytest
from PIL import Image

from chinchilla.core.geometry import Rect

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="needs a display to build GTK objects",
)


def test_render_keeps_the_selection_bright(tmp_path):
    from chinchilla.ui.overlay import SelectionOverlay

    background = Image.new("RGB", (400, 300), (250, 250, 250))
    overlay = SelectionOverlay(background=background)
    overlay.select_for_test(Rect(120, 100, 300, 150))
    path = overlay.render_to_png(tmp_path / "overlay.png")
    image = Image.open(path).convert("RGB")

    width, height = image.size
    assert width >= 300 and height >= 200
    inside = image.getpixel((140, 120))
    outside = image.getpixel((5, 5))
    assert sum(inside) > 600, inside
    # the veil dims the desktop without hiding it, and never dims the selection
    assert 300 < sum(outside) < 520, outside
    assert sum(outside) < 0.7 * sum(inside)

    handle = image.getpixel((270, 100))
    assert sum(handle) > 600, handle

    accent_pixels = sum(
        1
        for x in range(0, width, 7)
        if (lambda p: p[0] > 180 and 120 < p[1] < 220 and p[2] < 120)(
            image.getpixel((x, 100))
        )
    )
    assert accent_pixels > 0
    overlay.destroy()


def test_without_a_selection_everything_is_veiled():
    from chinchilla.ui.overlay import SelectionOverlay

    overlay = SelectionOverlay()
    path = overlay.render_to_png("/tmp/chin-empty-overlay.png")
    image = Image.open(path).convert("RGB")
    assert sum(image.getpixel((10, 10))) < 200
    overlay.destroy()


def test_live_frame_is_handed_to_the_window_as_a_pixbuf():
    """cairo paint contexts need python3-gi-cairo; the window must not."""
    from chinchilla.ui.overlay import SelectionOverlay

    overlay = SelectionOverlay(background=Image.new("RGB", (200, 150), (255, 255, 255)))
    overlay.select_for_test(Rect(20, 20, 100, 60))

    overlay._repaint()

    pixbuf = overlay._image.get_pixbuf()
    assert pixbuf is not None
    assert (pixbuf.get_width(), pixbuf.get_height()) == (
        overlay._screen.width,
        overlay._screen.height,
    )
    assert pixbuf.get_pixels()[:4] != b"\x00\x00\x00\x00"
    overlay.destroy()
