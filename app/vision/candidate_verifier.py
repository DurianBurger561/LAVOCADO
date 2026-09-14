"""Original-resolution local rechecks for visual candidates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.vision.preprocessor import FramePreprocessor
from app.vision.regions import Region
from app.vision.violation_policy import (
    DetectionTier,
    ThresholdPolicy,
    ViolationEvidence,
)


class LocalNudityDetector(Protocol):
    def detect(
        self, frame: np.ndarray, *, input_size: int, frame_sequence: int
    ) -> list[ViolationEvidence]: ...


@dataclass(frozen=True, slots=True)
class RecheckResult:
    region: Region
    hit: ViolationEvidence | None


class CandidateVerifier:
    """Run a local detector on a selected original-resolution ROI or tile."""

    def __init__(
        self,
        detector: LocalNudityDetector | None,
        *,
        threshold_policy: ThresholdPolicy,
        tile_input_size: int,
        enabled: bool = True,
    ) -> None:
        self.detector = detector
        self.threshold_policy = threshold_policy
        self.tile_input_size = tile_input_size
        self.enabled = enabled

    def strong_hit(self, crop: np.ndarray, *, frame_sequence: int) -> ViolationEvidence | None:
        if self.detector is None or not isinstance(crop, np.ndarray):
            return None
        evidence = self.detector.detect(
            crop, input_size=self.tile_input_size, frame_sequence=frame_sequence
        )
        strong = [
            item
            for item in evidence
            if self.threshold_policy.tier(item.confidence, item.label, item.model)
            is DetectionTier.STRONG
        ]
        return max(strong, key=lambda item: item.confidence, default=None)

    def context_recheck(
        self,
        prepared: FramePreprocessor,
        box: Sequence[int | float],
        *,
        model_shape: Sequence[int],
        expansion: float,
    ) -> RecheckResult | None:
        if not self.enabled or self.detector is None:
            return None
        cropped = prepared.context_crop(box, model_shape, expansion)
        if cropped is None:
            return None
        image, region = cropped
        return RecheckResult(region, self.strong_hit(image, frame_sequence=prepared.frame.sequence))

    def region_recheck(
        self, prepared: FramePreprocessor, region: Region
    ) -> RecheckResult | None:
        if self.detector is None:
            return None
        crop = prepared.crop_xyxy(region)
        if crop is None:
            return None
        return RecheckResult(region, self.strong_hit(crop, frame_sequence=prepared.frame.sequence))
