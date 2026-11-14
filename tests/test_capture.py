import io

import pytest
from PIL import Image

from chinchilla.core import capture
from chinchilla.core.geometry import Rect


@pytest.fixture()
def sample(tmp_path, monkeypatch):
    image = Image.new("RGB", (800, 400), (250, 250, 250))
    image.paste((20, 20, 20), (400, 200, 800, 400))
    path = tmp_path / "screen.png"
    image.save(path)
    monkeypatch.setenv("CHINCHILLA_CAPTURE_SOURCE", str(path))
    return path


def test_file_backend_is_used_first(sample):
    grab = capture.grab_screen()
    assert grab.backend == "file"
    assert grab.image.size == (800, 400)


def test_crop_uses_screen_coordinates():
    image = Image.new("RGB", (1600, 900), (255, 255, 255))
    image.paste((0, 0, 0), (200, 100, 400, 200))
    cropped = capture.crop(image, Rect(200, 100, 200, 100), (1600, 900))
    assert cropped.size == (200, 100)
    assert cropped.getpixel((10, 10)) == (0, 0, 0)


def test_crop_scales_between_image_and_screen():
    image = Image.new("RGB", (800, 400), (255, 255, 255))
    cropped = capture.crop(image, Rect(400, 200, 400, 200), (1600, 800))
    assert cropped.size == (200, 100)


def test_encode_limits_the_long_side():
    image = Image.new("RGB", (4000, 1000), (10, 200, 30))
    data = capture.encode_jpeg(image, max_side=1000)
    decoded = Image.open(io.BytesIO(data))
    assert max(decoded.size) == 1000


def test_save_jpeg_writes_a_file(tmp_path):
    image = Image.new("RGB", (120, 60), (30, 60, 90))
    path = capture.save_jpeg(image, tmp_path / "out" / "shot.jpg")
    assert path.exists() and Image.open(path).size == (120, 60)


def test_grab_screen_reports_what_went_wrong(tmp_path, monkeypatch):
    monkeypatch.setenv("CHINCHILLA_CAPTURE_SOURCE", str(tmp_path / "missing.png"))
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(capture, "_bus_has_owner", lambda _name: False)
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(capture.CaptureError) as error:
        capture.grab_screen()
    assert "no capture backend" in str(error.value)


def test_preferred_backend_is_tried_first(sample):
    grab = capture.grab_screen(preferred="portal")
    assert grab.backend == "file"


def test_grab_screen_remembers_the_parent_window(sample):
    capture.grab_screen(parent="x11:0x4a00007")

    assert capture.parent_window() == "x11:0x4a00007"
    capture.set_parent_window(None)
    assert capture.parent_window() == ""
