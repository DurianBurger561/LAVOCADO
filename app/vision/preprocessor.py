"""Per-frame BGR preparation for detector and context inputs.

Instances are deliberately short lived: one instance belongs to one captured
generation, so cached pixel buffers cannot leak into later scans.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.platforms.capture.models import CaptureFrame, Rect
from app.vision.regions import (
    Region,
    crop_region,
    expand_region,
    map_box_to_original,
    overlapping_tile_regions,
    subdivide_region,
)


@dataclass(frozen=True, slots=True)
class TileSpec:
    rows: int
    columns: int
    overlap: float = 0.0


@dataclass(frozen=True, slots=True)
class FrameRegion:
    region: Region
    image: np.ndarray = field(compare=False, repr=False)


class FramePreprocessor:
    """Prepare one canonical frame and cache transformations within that frame."""

    def __init__(self, frame: CaptureFrame) -> None:
        self.frame = frame
        self._resized: dict[int, np.ndarray] = {}
        self._rgb: np.ndarray | None = None
        self._crops: dict[Region, np.ndarray] = {}
        self._resized_crops: dict[tuple[Region, int], np.ndarray] = {}
        self._tiles: dict[TileSpec, tuple[FrameRegion, ...]] = {}

    @property
    def original(self) -> np.ndarray:
        return self.frame.image

    def require_frame(self, frame: CaptureFrame) -> None:
        if self.frame is not frame:
            raise ValueError("prepared pixels belong to a different capture frame")

    @staticmethod
    def to_rgb(image: np.ndarray) -> np.ndarray:
        """Return a contiguous RGB array without exposing a Pillow contract."""

        if (
            not isinstance(image, np.ndarray)
            or image.dtype != np.uint8
            or image.ndim != 3
            or image.shape[2] != 3
            or not image.size
        ):
            raise ValueError("expected a nonempty BGR uint8 H x W x 3 image")
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    def rgb(self) -> np.ndarray:
        if self._rgb is None:
            self._rgb = self.to_rgb(self.original)
        return self._rgb

    @staticmethod
    def _resize_long_edge(image: np.ndarray, size: int) -> np.ndarray:
        if size < 1:
            raise ValueError("size must be positive")
        height, width = image.shape[:2]
        if min(height, width) < 1:
            raise ValueError("cannot resize an empty image")
        long_edge = max(height, width)
        if long_edge <= size:
            return image
        scale = size / long_edge
        target = (max(1, round(width * scale)), max(1, round(height * scale)))
        return np.ascontiguousarray(cv2.resize(image, target, interpolation=cv2.INTER_AREA))

    def resized_long_edge(self, size: int) -> np.ndarray:
        if size not in self._resized:
            self._resized[size] = self._resize_long_edge(self.original, size)
        return self._resized[size]

    def crop(self, rect: Rect) -> np.ndarray | None:
        return self.crop_xyxy(
            (rect.left, rect.top, rect.left + rect.width, rect.top + rect.height)
        )

    def crop_xyxy(self, region: Region) -> np.ndarray | None:
        height, width = self.original.shape[:2]
        left, top, right, bottom = region
        clamped = (
            max(0, min(width, left)),
            max(0, min(height, top)),
            max(0, min(width, right)),
            max(0, min(height, bottom)),
        )
        if clamped[2] <= clamped[0] or clamped[3] <= clamped[1]:
            return None
        if clamped not in self._crops:
            cropped = crop_region(self.original, clamped)
            if cropped is None:
                return None
            self._crops[clamped] = cropped
        return self._crops[clamped]

    def resized_crop(self, rect: Rect, size: int) -> np.ndarray | None:
        region = (rect.left, rect.top, rect.left + rect.width, rect.top + rect.height)
        crop = self.crop_xyxy(region)
        if crop is None:
            return None
        height, width = self.original.shape[:2]
        clamped = (
            max(0, min(width, region[0])),
            max(0, min(height, region[1])),
            max(0, min(width, region[2])),
            max(0, min(height, region[3])),
        )
        key = (clamped, size)
        if key not in self._resized_crops:
            self._resized_crops[key] = self._resize_long_edge(crop, size)
        return self._resized_crops[key]

    def context_crop(
        self,
        box: Sequence[int | float],
        model_shape: Sequence[int],
        expansion: float,
    ) -> tuple[np.ndarray, Region] | None:
        mapped = map_box_to_original(box, model_shape, self.original.shape)
        if mapped is None:
            return None
        region = expand_region(mapped, self.original.shape, expansion)
        if region is None:
            return None
        crop = self.crop_xyxy(region)
        return None if crop is None else (crop, region)

    def tiles(self, spec: TileSpec) -> tuple[FrameRegion, ...]:
        if spec not in self._tiles:
            regions = overlapping_tile_regions(
                self.original.shape, spec.rows, spec.columns, spec.overlap
            )
            self._tiles[spec] = tuple(
                FrameRegion(region, crop)
                for region in regions
                if (crop := self.crop_xyxy(region)) is not None
            )
        return self._tiles[spec]

    def subtiles(
        self, region: Region, rows: int = 2, columns: int = 2
    ) -> tuple[FrameRegion, ...]:
        return tuple(
            FrameRegion(subregion, crop)
            for subregion in subdivide_region(region, rows, columns)
            if (crop := self.crop_xyxy(subregion)) is not None
        )
