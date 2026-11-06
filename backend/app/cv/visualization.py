"""Draw geometry overlays. Colors are supplied by configuration, not chosen here."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.cv.types import EarlobeAnchor, EarringAnchor
from app.utils.geometry import ellipse_radii


def hex_to_bgr(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        return (255, 255, 255)
    red = int(cleaned[0:2], 16)
    green = int(cleaned[2:4], 16)
    blue = int(cleaned[4:6], 16)
    return (blue, green, red)


class OverlayPalette:
    def __init__(self, earlobe: str, earring: str, zone: str, inner_zone: str, vector: str) -> None:
        self.earlobe = hex_to_bgr(earlobe)
        self.earring = hex_to_bgr(earring)
        self.zone = hex_to_bgr(zone)
        self.inner_zone = hex_to_bgr(inner_zone)
        self.vector = hex_to_bgr(vector)


def annotate_frame(
    image_bgr: np.ndarray,
    earlobe: EarlobeAnchor | None,
    earring: EarringAnchor | None,
    *,
    palette: OverlayPalette,
    pass_threshold: float,
    fail_threshold: float,
    zone_y_scale: float = 1.0,
    normalized_distance: float | None = None,
) -> np.ndarray:
    canvas = image_bgr.copy()
    height, width = canvas.shape[:2]
    if earlobe is None:
        return canvas

    center = (int(earlobe.x * width), int(earlobe.y * height))
    outer_rx, outer_ry = ellipse_radii(earlobe.ear_width, fail_threshold, zone_y_scale)
    inner_rx, inner_ry = ellipse_radii(earlobe.ear_width, pass_threshold, zone_y_scale)
    outer_axes = (max(4, int(outer_rx * width)), max(4, int(outer_ry * height)))
    inner_axes = (max(3, int(inner_rx * width)), max(3, int(inner_ry * height)))
    cv2.ellipse(canvas, center, outer_axes, 0, 0, 360, palette.zone, 2)
    cv2.ellipse(canvas, center, inner_axes, 0, 0, 360, palette.inner_zone, 1)
    cv2.circle(canvas, center, 6, palette.earlobe, -1)

    if earring and earring.x is not None and earring.y is not None:
        earring_point = (int(earring.x * width), int(earring.y * height))
        cv2.line(canvas, center, earring_point, palette.vector, 2)
        cv2.circle(canvas, earring_point, 6, palette.earring, -1)
        if normalized_distance is not None and math_isfinite(normalized_distance):
            label_x = int((center[0] + earring_point[0]) / 2) + 8
            label_y = int((center[1] + earring_point[1]) / 2)
            cv2.putText(
                canvas,
                f"{normalized_distance:.3f}",
                (label_x, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                palette.vector,
                1,
                cv2.LINE_AA,
            )
    return canvas


def draw_placed_earring(
    image_bgr: np.ndarray,
    x: float,
    y: float,
    ear_width: float | None = None,
) -> np.ndarray:
    """Paint a drop earring whose hook sits on the attachment point."""
    canvas = image_bgr.copy()
    height, width = canvas.shape[:2]
    anchor_x = int(np.clip(x, 0, 1) * width)
    anchor_y = int(np.clip(y, 0, 1) * height)
    ear_px = int((ear_width or 0.045) * width)
    ear_px = max(16, min(ear_px, width // 5))
    drop = int(ear_px * 2.4)
    layer = np.zeros((height, width, 4), dtype=np.uint8)
    gold = (40, 190, 230, 235)
    gem = (70, 150, 210, 235)
    edge = (20, 110, 170, 255)
    stud_radius = max(3, ear_px // 9)
    cv2.circle(layer, (anchor_x, anchor_y), stud_radius, gold, -1, lineType=cv2.LINE_AA)
    wire_end = (anchor_x, min(height - 1, anchor_y + drop // 3))
    cv2.line(layer, (anchor_x, anchor_y), wire_end, gold, 2, lineType=cv2.LINE_AA)
    gem_center = (anchor_x, min(height - 1, anchor_y + int(drop * 0.62)))
    axes = (max(5, ear_px // 3), max(8, int(drop * 0.32)))
    cv2.ellipse(layer, gem_center, axes, 0, 0, 360, gem, -1, lineType=cv2.LINE_AA)
    cv2.ellipse(layer, gem_center, axes, 0, 0, 360, edge, 1, lineType=cv2.LINE_AA)
    highlight = (gem_center[0] - axes[0] // 3, gem_center[1] - axes[1] // 3)
    cv2.circle(layer, highlight, max(2, axes[0] // 5), (180, 220, 245, 220), -1, lineType=cv2.LINE_AA)
    alpha = layer[:, :, 3:4].astype(np.float32) / 255.0
    color = layer[:, :, :3].astype(np.float32)
    base = canvas.astype(np.float32)
    blended = base * (1.0 - alpha) + color * alpha
    return blended.astype(np.uint8)


def image_from_bytes(payload: bytes) -> np.ndarray | None:
    if not payload:
        return None
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        return None
    return image


def prepare_catalog_sprite(image: np.ndarray) -> np.ndarray | None:
    """Turn a catalog product photo into a cropped cutout of the jewelry."""
    sprite = _as_bgra(image)
    if sprite is None:
        return None
    if _has_cutout_alpha(sprite):
        cropped = _crop_to_alpha(sprite)
    else:
        cropped = _crop_to_alpha(_key_studio_backdrop(sprite))
    if cropped is None or cropped.shape[0] < 8 or cropped.shape[1] < 8:
        return None
    return _limit_sprite_edge(cropped, 640)


def catalog_sprite_layout(sprite: np.ndarray) -> dict:
    """Studs sit on the lobe. Taller pieces hang from the piercing."""
    height, width = sprite.shape[:2]
    aspect = height / max(1, width)
    hang = aspect >= 1.45
    return {"aspect": float(aspect), "hang": hang, "width_ratio": 1.0 if hang else 0.62}


def save_catalog_sprite(image: np.ndarray, path: Path) -> bool:
    sprite = prepare_catalog_sprite(image)
    if sprite is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(path), sprite))


def composite_catalog_earring(
    image_bgr: np.ndarray,
    sprite_path: Path,
    x: float,
    y: float,
    ear_width: float | None = None,
) -> np.ndarray:
    """Place the selected catalog photo on the earlobe."""
    sprite = cv2.imread(str(sprite_path), cv2.IMREAD_UNCHANGED)
    prepared = prepare_catalog_sprite(sprite) if sprite is not None else None
    if prepared is None:
        return draw_placed_earring(image_bgr, x, y, ear_width)
    layout = catalog_sprite_layout(prepared)
    height, width = image_bgr.shape[:2]
    target_w = catalog_target_width(ear_width, width, layout["width_ratio"])
    scale = target_w / max(1, prepared.shape[1])
    target_h = max(8, int(prepared.shape[0] * scale))
    prepared = cv2.resize(prepared, (target_w, target_h), interpolation=cv2.INTER_AREA)
    anchor_x = int(np.clip(x, 0, 1) * width)
    anchor_y = int(np.clip(y, 0, 1) * height)
    left = anchor_x - target_w // 2
    top = anchor_y if layout["hang"] else anchor_y - target_h // 2
    return _blend_sprite(image_bgr, prepared, left, top)


def catalog_target_width(ear_width: float | None, frame_width: int, width_ratio: float) -> int:
    scaled = (ear_width or 0.08) * frame_width * width_ratio
    capped = min(scaled, frame_width * 0.18)
    return max(22, int(capped))


def _as_bgra(image: np.ndarray) -> np.ndarray | None:
    if image is None or image.size == 0:
        return None
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    if image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    if image.shape[2] == 4:
        return image.copy()
    return None


def _has_cutout_alpha(sprite: np.ndarray) -> bool:
    alpha = sprite[:, :, 3]
    transparent = float(np.mean(alpha < 16))
    opaque = float(np.mean(alpha > 240))
    return transparent > 0.05 and opaque > 0.02


def _studio_backdrop(image_bgr: np.ndarray) -> np.ndarray | None:
    height, width = image_bgr.shape[:2]
    if height < 2 or width < 2:
        return None
    corners = np.stack(
        [
            image_bgr[0, 0],
            image_bgr[0, width - 1],
            image_bgr[height - 1, 0],
            image_bgr[height - 1, width - 1],
        ]
    ).astype(np.float32)
    if float(corners.std(axis=0).max()) > 18:
        return None
    median = np.median(corners, axis=0)
    if float(median.min()) < 170:
        return None
    return median


def _key_studio_backdrop(sprite: np.ndarray) -> np.ndarray:
    result = sprite.copy()
    bgr = np.ascontiguousarray(result[:, :, :3])
    if _studio_backdrop(bgr) is None:
        result[:, :, 3] = 255
        return result
    height, width = bgr.shape[:2]
    mask = np.zeros((height + 2, width + 2), np.uint8)
    flags = cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
    seeds = (
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
        (width // 2, 0),
        (width // 2, height - 1),
        (0, height // 2),
        (width - 1, height // 2),
    )
    for seed in seeds:
        if mask[seed[1] + 1, seed[0] + 1]:
            continue
        cv2.floodFill(bgr, mask, seed, (0, 0, 0), (32, 32, 32), (32, 32, 32), flags)
    backdrop = mask[1:-1, 1:-1] > 0
    alpha = np.where(backdrop, 0, 255).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    result[:, :, 3] = alpha
    return result


def _crop_to_alpha(sprite: np.ndarray, threshold: int = 20) -> np.ndarray | None:
    ys, xs = np.where(sprite[:, :, 3] > threshold)
    if len(xs) == 0:
        return None
    return sprite[int(ys.min()) : int(ys.max()) + 1, int(xs.min()) : int(xs.max()) + 1]


def _limit_sprite_edge(sprite: np.ndarray, max_edge: int) -> np.ndarray:
    height, width = sprite.shape[:2]
    edge = max(height, width)
    if edge <= max_edge:
        return sprite
    scale = max_edge / edge
    return cv2.resize(
        sprite,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def _blend_sprite(image_bgr: np.ndarray, sprite: np.ndarray, left: int, top: int) -> np.ndarray:
    canvas = image_bgr.copy()
    height, width = canvas.shape[:2]
    sprite_h, sprite_w = sprite.shape[:2]
    x0 = max(0, left)
    y0 = max(0, top)
    x1 = min(width, left + sprite_w)
    y1 = min(height, top + sprite_h)
    if x0 >= x1 or y0 >= y1:
        return canvas
    region = sprite[y0 - top : y0 - top + (y1 - y0), x0 - left : x0 - left + (x1 - x0)]
    alpha = region[:, :, 3:4].astype(np.float32) / 255.0
    base = canvas[y0:y1, x0:x1].astype(np.float32)
    canvas[y0:y1, x0:x1] = (base * (1.0 - alpha) + region[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return canvas


def save_image(path: Path, image_bgr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image_bgr):
        raise ValueError(f"Unable to write image {path.name}")


def math_isfinite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
