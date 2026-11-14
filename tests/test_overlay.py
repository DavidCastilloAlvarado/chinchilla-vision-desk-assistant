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
    assert sum(outside) < 200, outside

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
