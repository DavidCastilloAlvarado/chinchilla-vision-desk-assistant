"""Cairo drawing helpers.

Images are handed to cairo through raw pixel buffers instead of the
Gdk/PangoCairo converters, because ``python3-gi-cairo`` is not available on
every host. Text uses cairo's built in font API for the same reason.
"""

from __future__ import annotations

import cairo
from PIL import Image

FONT_FAMILY = "DejaVu Sans"


def surface_from_image(
    image: Image.Image, alpha: bool = False
) -> tuple[cairo.ImageSurface, bytearray]:
    """PIL image to a cairo surface in the native byte order.

    Cairo stores RGB24 and ARGB32 as 32-bit pixels (B, G, R, X/A).
    """
    rgba = image.convert("RGBA").tobytes()
    data = bytearray(len(rgba))
    data[0::4] = rgba[2::4]
    data[1::4] = rgba[1::4]
    data[2::4] = rgba[0::4]
    if alpha:
        fmt = cairo.FORMAT_ARGB32
        data[3::4] = rgba[3::4]
        for offset in range(0, len(data), 4):
            a = data[offset + 3]
            if a != 255:
                data[offset] = data[offset] * a // 255
                data[offset + 1] = data[offset + 1] * a // 255
                data[offset + 2] = data[offset + 2] * a // 255
    else:
        fmt = cairo.FORMAT_RGB24
        data[3::4] = b"\xff" * (len(rgba) // 4)
    stride = cairo.ImageSurface.format_stride_for_width(fmt, image.width)
    surface = cairo.ImageSurface.create_for_data(
        data, fmt, image.width, image.height, stride
    )
    return surface, data


def set_font(cr, size: float, bold: bool = False) -> None:
    weight = cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL
    cr.select_font_face(FONT_FAMILY, cairo.FONT_SLANT_NORMAL, weight)
    cr.set_font_size(size)


_MEASURE_SURFACE = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)
_MEASURE_CR = cairo.Context(_MEASURE_SURFACE)


def text_size(text: str, size: float, bold: bool = False) -> tuple[int, int]:
    set_font(_MEASURE_CR, size, bold)
    extents = _MEASURE_CR.text_extents(text)
    ascent, descent = _MEASURE_CR.font_extents()[:2]
    return (int(round(extents[4])), int(round(ascent + descent)))


def draw_text(
    cr,
    text: str,
    x: float,
    y: float,
    size: float = 11,
    color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    bold: bool = False,
    alpha: float = 1.0,
) -> tuple[int, int]:
    """Draw text with its top left corner at x, y."""
    set_font(cr, size, bold)
    ascent = cr.font_extents()[0]
    cr.set_source_rgba(color[0], color[1], color[2], alpha)
    cr.move_to(x, y + ascent)
    cr.show_text(text)
    return text_size(text, size, bold)
