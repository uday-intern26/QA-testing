import cv2
import numpy as np

from app.cv.types import EarlobeAnchor
from app.services.live_jewelry_overlay import earlobe_placements, paint_preview, sprite_data_url


def test_live_preview_hangs_jewelry_from_the_earlobe(tmp_path):
    frame = tmp_path / "frame.png"
    cv2.imwrite(str(frame), np.full((200, 200, 3), 240, dtype=np.uint8))
    destination = tmp_path / "live_preview.png"
    paint_preview(frame, [{"x": 0.5, "y": 0.3, "ear_width": 0.1, "side": "left"}], None, destination)
    painted = cv2.imread(str(destination))
    original = np.full((200, 200, 3), 240, dtype=np.uint8)
    assert int(np.abs(painted.astype(int) - original.astype(int)).sum()) > 0


def test_sprite_data_url_is_a_transparent_png():
    url = sprite_data_url(None)
    assert url.startswith("data:image/png;base64,")


def test_live_preview_paints_the_catalog_photo(tmp_path):
    frame = tmp_path / "frame.png"
    cv2.imwrite(str(frame), np.full((240, 240, 3), 255, dtype=np.uint8))
    photo = np.full((120, 48, 3), 250, dtype=np.uint8)
    cv2.rectangle(photo, (10, 8), (38, 110), (25, 35, 200), -1)
    sprite = tmp_path / "selected_earring.png"
    cv2.imwrite(str(sprite), photo)
    destination = tmp_path / "live_preview.png"
    paint_preview(
        frame,
        [{"x": 0.5, "y": 0.28, "ear_width": 0.14, "side": "left"}],
        sprite,
        destination,
    )
    painted = cv2.imread(str(destination))
    anchor_y = int(0.28 * 240)
    assert painted[anchor_y + 10, 120, 2] > 120
    assert painted[max(0, anchor_y - 6), 120].tolist() == [255, 255, 255]


def test_overlay_uses_each_detected_earlobe():
    class Detector:
        def detect(self, _face, side):
            if side == "right":
                return None, "missing"
            return (
                EarlobeAnchor(side="left", x=0.2, y=0.4, confidence=1, ear_width=0.05, ear_height=0.08),
                None,
            )

    assert earlobe_placements(None, Detector()) == [
        {"side": "left", "x": 0.2, "y": 0.4, "ear_width": 0.05}
    ]
