from chinchilla.core.geometry import Rect, clamp, fit, from_points, is_usable, nudge


def test_points_in_any_direction_give_the_same_rect():
    assert from_points(10, 20, 110, 220) == from_points(110, 220, 10, 20)
    assert from_points(110, 220, 10, 20) == Rect(10, 20, 100, 200)


def test_points_are_clamped_to_the_screen():
    rect = from_points(-50, -80, 5000, 4000, bounds=(1280, 800))
    assert rect == Rect(0, 0, 1280, 800)


def test_single_click_is_not_usable():
    assert not is_usable(from_points(10, 10, 12, 14))
    assert is_usable(Rect(0, 0, 320, 200))


def test_nudge_keeps_rect_inside():
    rect = Rect(100, 100, 200, 100)
    assert nudge(rect, -500, -500, 1280, 800) == Rect(0, 0, 200, 100)
    assert nudge(rect, 5000, 5000, 1280, 800) == Rect(1080, 700, 200, 100)
    assert nudge(rect, 5, -5, 1280, 800) == Rect(105, 95, 200, 100)


def test_clamp_and_fit():
    assert clamp(Rect(1200, 700, 400, 400), 1280, 800) == Rect(1200, 700, 80, 100)
    assert fit(Rect(10, 20, 100, 50), 0.5) == Rect(5, 10, 50, 25)
    assert fit(Rect(1, 1, 1, 1), 0.1).width == 1


def test_box_matches_pil_convention():
    assert Rect(10, 20, 30, 40).box() == (10, 20, 40, 60)
