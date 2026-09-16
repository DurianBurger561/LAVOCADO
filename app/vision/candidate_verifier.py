"""Original-resolution local rechecks for visual candidates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.vision.detectors.base import PrimaryDetector
from app.vision.preprocessor import FramePreprocessor, PreparedFrame
from app.vision.regions import Region
from app.vision.violation_policy import (
    DetectionTier,
    ThresholdPolicy,
    ViolationEvidence,
)


@dataclass(frozen=True, slots=True)
class RecheckResult:
    region: Region
    hit: ViolationEvidence | None


class CandidateVerifier:
    """Run a local detector on a selected original-resolution ROI or tile."""

    def __init__(
        self,
        detector: PrimaryDetector | None,
        *,
        threshold_policy: ThresholdPolicy,
        tile_input_size: int,
        enabled: bool = True,
    ) -> None:
        self.detector = detector
        self.threshold_policy = threshold_policy
        self.tile_input_size = tile_input_size
        self.enabled = enabled

    def strong_hit(self, prepared: PreparedFrame) -> ViolationEvidence | None:
        if self.detector is None:
            return None
        evidence = self.detector.detect(prepared)
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
        _image, region = cropped
        model_frame = prepared.prepare_region(region, self.tile_input_size)
        if model_frame is None:
            return None
        return RecheckResult(region, self.strong_hit(model_frame))

    def region_recheck(
        self, prepared: FramePreprocessor, region: Region
    ) -> RecheckResult | None:
        if self.detector is None:
            return None
        model_frame = prepared.prepare_region(region, self.tile_input_size)
        if model_frame is None:
            return None
        return RecheckResult(region, self.strong_hit(model_frame))
