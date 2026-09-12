"""Coordinate mapping and in-memory crop helpers for vision decisions."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

Region = tuple[int, int, int, int]


def map_box_to_original(
    box: Sequence[int | float],
    model_shape: Sequence[int],
    original_shape: Sequence[int],
) -> Region | None:
    """Map a NudeNet ``[x, y, width, height]`` box to original XYXY pixels."""

    if len(box) != 4 or len(model_shape) < 2 or len(original_shape) < 2:
        return None
    model_height, model_width = int(model_shape[0]), int(model_shape[1])
    original_height, original_width = int(original_shape[0]), int(original_shape[1])
    if min(model_height, model_width, original_height, original_width) <= 0:
        return None

    x, y, width, height = (float(value) for value in box)
    if not all(math.isfinite(value) for value in (x, y, width, height)):
        return None
    if width <= 0 or height <= 0:
        return None

    model_left = max(0.0, min(float(model_width), x))
    model_top = max(0.0, min(float(model_height), y))
    model_right = max(0.0, min(float(model_width), x + width))
    model_bottom = max(0.0, min(float(model_height), y + height))
    if model_right <= model_left or model_bottom <= model_top:
        return None

    scale_x = original_width / model_width
    scale_y = original_height / model_height
    left = max(0, min(original_width, math.floor(model_left * scale_x)))
    top = max(0, min(original_height, math.floor(model_top * scale_y)))
    right = max(0, min(original_width, math.ceil(model_right * scale_x)))
    bottom = max(0, min(original_height, math.ceil(model_bottom * scale_y)))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def expand_region(
    region: Region,
    image_shape: Sequence[int],
    factor: float,
) -> Region | None:
    """Expand an XYXY region around its centre and clamp it to the image."""

    if len(image_shape) < 2 or not math.isfinite(factor) or factor < 1.0:
        return None
    image_height, image_width = int(image_shape[0]), int(image_shape[1])
    left, top, right, bottom = region
    if image_height <= 0 or image_width <= 0 or right <= left or bottom <= top:
        return None

    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    expanded_width = (right - left) * factor
    expanded_height = (bottom - top) * factor
    expanded_left = max(0, math.floor(center_x - expanded_width / 2))
    expanded_top = max(0, math.floor(center_y - expanded_height / 2))
    expanded_right = min(image_width, math.ceil(center_x + expanded_width / 2))
    expanded_bottom = min(image_height, math.ceil(center_y + expanded_height / 2))
    if expanded_right <= expanded_left or expanded_bottom <= expanded_top:
        return None
    return expanded_left, expanded_top, expanded_right, expanded_bottom


def make_context_crop(
    original_frame: np.ndarray,
    box: Sequence[int | float],
    model_shape: Sequence[int],
    expansion: float,
) -> tuple[np.ndarray, Region] | None:
    """Map, expand, and copy a local context crop from an original frame."""

    mapped_region = map_box_to_original(box, model_shape, original_frame.shape)
    if mapped_region is None:
        return None
    context_region = expand_region(mapped_region, original_frame.shape, expansion)
    if context_region is None:
        return None
    left, top, right, bottom = context_region
    crop = np.ascontiguousarray(original_frame[top:bottom, left:right])
    if crop.size == 0:
        return None
    return crop, context_region
