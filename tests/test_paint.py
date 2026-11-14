from PIL import Image

from chinchilla.ui import paint
from chinchilla.ui.snapshot import render_cairo


def test_surface_from_rgb_image_keeps_colour():
    image = Image.new("RGB", (4, 2), (10, 20, 30))
    surface, data = paint.surface_from_image(image)
    assert surface.get_width() == 4
    assert bytes(data[:3]) == bytes((30, 20, 10))


def test_surface_with_alpha_premultiplies():
    image = Image.new("RGBA", (2, 1), (200, 100, 50, 0))
    _surface, data = paint.surface_from_image(image, alpha=True)
    assert bytes(data[:4]) == bytes((0, 0, 0, 0))


def test_text_is_measured_and_drawn():
    assert paint.text_size("640 x 480", 12, bold=True)[0] > 20
    assert paint.text_size("", 12)[1] > 0

    def render(cr, width, height):
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        paint.draw_text(cr, "hello", 8, 8, 14, (1, 1, 1), True)

    target = render_cairo(render, "/tmp/chin-text-test.png", 80, 30)
    surface = __import__("cairo").ImageSurface.create_from_png(str(target))
    assert surface.get_width() == 80
    target.unlink()
