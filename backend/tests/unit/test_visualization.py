import cv2
import numpy as np

from app.cv.visualization import (
    catalog_sprite_layout,
    composite_catalog_earring,
    draw_placed_earring,
    prepare_catalog_sprite,
)


def test_placed_earring_hangs_below_the_attachment_point():
    image = np.full((200, 200, 3), 240, dtype=np.uint8)
    placed = draw_placed_earring(image, 0.5, 0.4, 0.08)
    anchor_y = int(0.4 * 200)
    below = placed[anchor_y + 12 : anchor_y + 40, 90:110]
    assert below.mean() < image[anchor_y + 12 : anchor_y + 40, 90:110].mean()


def test_catalog_photo_loses_its_white_backdrop_and_keeps_the_jewelry():
    photo = np.full((90, 70, 3), 255, dtype=np.uint8)
    cv2.ellipse(photo, (35, 48), (14, 28), 0, 0, 360, (30, 80, 190), -1)
    sprite = prepare_catalog_sprite(photo)
    assert sprite is not None
    assert sprite.shape[0] < 90
    assert sprite.shape[1] < 70
    assert int(sprite[:, :, 3].max()) > 200
    assert int(sprite[0, 0, 3]) < 40


def test_existing_cutout_is_cropped_to_the_jewelry():
    image = np.zeros((50, 50, 4), dtype=np.uint8)
    image[12:36, 18:34] = (40, 140, 210, 255)
    sprite = prepare_catalog_sprite(image)
    assert sprite is not None
    assert sprite.shape == (24, 16, 4)
    assert catalog_sprite_layout(sprite)["hang"] is True


def test_drop_hangs_from_the_lobe_and_stud_sits_on_it(tmp_path):
    frame = np.full((220, 220, 3), 255, dtype=np.uint8)
    drop = np.zeros((80, 24, 4), dtype=np.uint8)
    drop[:, :] = (20, 40, 180, 255)
    drop_path = tmp_path / "drop.png"
    cv2.imwrite(str(drop_path), drop)
    placed = composite_catalog_earring(frame, drop_path, 0.5, 0.35, 0.12)
    anchor_y = int(0.35 * 220)
    assert placed[anchor_y - 4, 110].tolist() == [255, 255, 255]
    assert placed[anchor_y + 8, 110, 2] > 100

    stud = np.zeros((28, 28, 4), dtype=np.uint8)
    stud[:, :] = (30, 160, 220, 255)
    stud_path = tmp_path / "stud.png"
    cv2.imwrite(str(stud_path), stud)
    placed = composite_catalog_earring(frame, stud_path, 0.5, 0.5, 0.2)
    anchor_y = 110
    assert placed[anchor_y - 4, 110, 1] < 250
    assert placed[anchor_y + 4, 110, 1] < 250
