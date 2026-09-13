"""App-agnostic screen change map used only to raise tile priority."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.vision.regions import Region

CHANGE_MAP_SIZE = (36, 64)  # height, width


@dataclass(frozen=True, slots=True)
class ChangeMap:
    gray: np.ndarray
    previous: np.ndarray | None
    difference: np.ndarray | None

    @property
    def global_ratio(self) -> float:
        if self.difference is None or self.difference.size == 0:
            return 0.0
        return float(np.mean(self.difference))


def _grayscale_map(image: np.ndarray, height: int = 36, width: int = 64) -> np.ndarray | None:
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or image.shape[0] < 1
        or image.shape[1] < 1
    ):
        return None
    src_h, src_w = image.shape[:2]
    row_indexes = np.linspace(0, src_h - 1, min(src_h, height), dtype=np.intp)
    column_indexes = np.linspace(0, src_w - 1, min(src_w, width), dtype=np.intp)
    sampled = image[row_indexes[:, None], column_indexes]
    blue = sampled[:, :, 0].astype(np.uint16)
    green = sampled[:, :, 1].astype(np.uint16)
    red = sampled[:, :, 2].astype(np.uint16)
    gray = (29 * blue + 150 * green + 77 * red) >> 8
    return np.ascontiguousarray(gray, dtype=np.uint8)


def build_change_map(
    current_frame: np.ndarray,
    previous_gray: np.ndarray | None,
    *,
    pixel_delta: int = 12,
) -> ChangeMap | None:
    gray = _grayscale_map(current_frame)
    if gray is None:
        return None
    if previous_gray is None or previous_gray.shape != gray.shape:
        return ChangeMap(gray=gray, previous=None, difference=None)
    delta = np.abs(gray.astype(np.int16) - previous_gray.astype(np.int16))
    difference = (delta >= pixel_delta).astype(np.float32)
    return ChangeMap(gray=gray, previous=previous_gray, difference=difference)


def tile_change_scores(
    change_map: ChangeMap | None,
    regions: tuple[Region, ...],
    image_shape: tuple[int, ...],
) -> list[float]:
    """Mean change inside each original-frame tile, mapped through the 64x36 grid."""

    if change_map is None or change_map.difference is None or len(image_shape) < 2:
        return [0.0 for _ in regions]
    image_height, image_width = int(image_shape[0]), int(image_shape[1])
    if image_height <= 0 or image_width <= 0:
        return [0.0 for _ in regions]
    map_h, map_w = change_map.difference.shape[:2]
    scores: list[float] = []
    for left, top, right, bottom in regions:
        map_left = max(0, min(map_w, int(left * map_w / image_width)))
        map_right = max(0, min(map_w, int(math_ceil(right * map_w / image_width))))
        map_top = max(0, min(map_h, int(top * map_h / image_height)))
        map_bottom = max(0, min(map_h, int(bottom * map_h / image_height)))
        if map_right <= map_left:
            map_right = min(map_w, map_left + 1)
        if map_bottom <= map_top:
            map_bottom = min(map_h, map_top + 1)
        patch = change_map.difference[map_top:map_bottom, map_left:map_right]
        scores.append(0.0 if patch.size == 0 else float(np.mean(patch)))
    return scores


def math_ceil(value: float) -> int:
    integer = int(value)
    return integer if integer == value else integer + 1
