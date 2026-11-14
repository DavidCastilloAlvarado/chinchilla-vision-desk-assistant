"""Rectangle maths for the selection overlay."""

from __future__ import annotations

from dataclasses import dataclass

MIN_SIZE = 8


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height

    def to_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    def box(self) -> tuple[int, int, int, int]:
        """Left, top, right, bottom - convenient for PIL crop."""
        return (self.x, self.y, self.right, self.bottom)


def from_points(
    x1: int, y1: int, x2: int, y2: int, bounds: tuple[int, int] | None = None
) -> Rect:
    """Build a rect from a drag between two points, handling any direction."""
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    if bounds is not None:
        max_w, max_h = bounds
        left = max(0, min(left, max_w))
        right = max(0, min(right, max_w))
        top = max(0, min(top, max_h))
        bottom = max(0, min(bottom, max_h))
    return Rect(left, top, max(0, right - left), max(0, bottom - top))


def clamp(rect: Rect, width: int, height: int) -> Rect:
    x = max(0, min(rect.x, width))
    y = max(0, min(rect.y, height))
    return Rect(x, y, max(0, min(rect.width, width - x)), max(0, min(rect.height, height - y)))


def nudge(rect: Rect, dx: int, dy: int, width: int, height: int) -> Rect:
    """Move a rect without letting it leave the screen."""
    x = max(0, min(rect.x + dx, width - rect.width))
    y = max(0, min(rect.y + dy, height - rect.height))
    return Rect(x, y, rect.width, rect.height)


def is_usable(rect: Rect, min_size: int = MIN_SIZE) -> bool:
    return rect.width >= min_size and rect.height >= min_size


def fit(rect: Rect, scale: float = 1.0) -> Rect:
    """Scale a rect, keeping integer pixels."""
    return Rect(
        int(round(rect.x * scale)),
        int(round(rect.y * scale)),
        max(1, int(round(rect.width * scale))),
        max(1, int(round(rect.height * scale))),
    )
