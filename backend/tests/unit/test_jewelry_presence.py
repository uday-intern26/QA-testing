"""Worn-jewelry frames are kept. Bare frames are not."""

from __future__ import annotations

import numpy as np

from app.cv.jewelry_presence import frame_wears_jewelry, jewelry_visible_in_image


def _shirt(width: int = 200, height: int = 280) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:] = (210, 190, 170)  # beige background, BGR
    # Orange shirt across the lower body. OpenCV hue for this orange is inside the skin band.
    image[int(height * 0.40) :, int(width * 0.22) : int(width * 0.78)] = (60, 90, 190)
    return image


def test_bare_shirt_is_not_a_worn_necklace():
    assert jewelry_visible_in_image(_shirt(), "necklace") is False


def test_beaded_necklace_across_the_chest_counts_as_worn():
    image = _shirt()
    height, width = image.shape[:2]
    y = int(height * 0.50)
    left = int(width * 0.34)
    right = int(width * 0.66)
    image[y - 3 : y + 3, left:right] = (180, 40, 20)  # blue beads
    image[y - 3 : y + 3, left + 8 : right : 12] = (40, 40, 210)  # red beads
    assert jewelry_visible_in_image(image, "necklace") is True


def test_small_logo_on_the_shirt_does_not_count_as_a_necklace():
    image = _shirt()
    height, width = image.shape[:2]
    y = int(height * 0.62)
    x = int(width * 0.30)
    image[y : y + 8, x : x + 10] = (200, 40, 40)
    assert jewelry_visible_in_image(image, "necklace") is False


def test_published_attachment_counts_as_worn_even_without_pixels():
    assert frame_wears_jewelry(_shirt(), "necklace", {"center": {"x": 0.5, "y": 0.5, "visible": True}}) is True


def test_blank_frame_is_not_a_bracelet_and_has_no_subject():
    from app.cv.jewelry_presence import keep_capture_frame, subject_visible

    image = np.full((200, 320, 3), 235, dtype=np.uint8)
    assert jewelry_visible_in_image(image, "bracelet") is False
    assert subject_visible(image) is False
    assert keep_capture_frame(image, "bracelet", storefront_ar=True, jewelry_confirmed=True) is False


def test_arm_on_a_plain_backdrop_is_kept_after_jewelry_is_laid():
    from app.cv.jewelry_presence import keep_capture_frame, subject_visible

    image = np.full((200, 320, 3), 235, dtype=np.uint8)
    image[95:145, 0:230] = (90, 120, 176)
    image[108:116, 190:310] = (90, 120, 176)
    image[124:132, 190:300] = (90, 120, 176)
    assert subject_visible(image) is True
    assert keep_capture_frame(image, "bracelet", storefront_ar=False, jewelry_confirmed=False) is jewelry_visible_in_image(
        image, "bracelet"
    )
    assert keep_capture_frame(image, "bracelet", storefront_ar=False, jewelry_confirmed=True) is True
    assert keep_capture_frame(image, "bracelet", storefront_ar=True) is True


def test_storefront_ar_counts_as_worn_when_the_attachment_is_unreadable():
    image = np.full((80, 120, 3), 240, dtype=np.uint8)
    state = {"anchor_source": "storefront_ar", "qa_status": "ready", "anchor_stage": "AR_VISIBLE"}
    assert jewelry_visible_in_image(image, "bracelet") is False
    assert frame_wears_jewelry(image, "bracelet", state) is True
