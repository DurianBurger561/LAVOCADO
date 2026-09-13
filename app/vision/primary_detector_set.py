"""Run enabled primary models and merge their typed visual evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.vision.detectors.base import DetectionEvidence, detection_to_violation
from app.vision.preprocessor import FramePreprocessor
from app.vision.violation_policy import ViolationEvidence
from app.vision.yolo_adapter import Yolo11Adapter


class PrimaryModel(Protocol):
    def detect(
        self, image: np.ndarray, *, input_size: int
    ) -> list[DetectionEvidence]: ...


@dataclass(frozen=True, slots=True)
class PrimaryDetection:
    """One inference result; no classification or protection action."""

    primary: tuple[DetectionEvidence, ...]
    supplementary: tuple[ViolationEvidence, ...]
    evidence: tuple[ViolationEvidence, ...]


class PrimaryDetectorSet:
    """Own model invocation, leaving thresholds to VisualDecisionEngine."""

    def __init__(
        self,
        primary: PrimaryModel,
        *,
        supplementary: Yolo11Adapter | None = None,
        full_input_size: int = 640,
    ) -> None:
        self.primary = primary
        self.supplementary = supplementary
        self.full_input_size = full_input_size

    def detect(self, prepared: FramePreprocessor) -> PrimaryDetection:
        sequence = prepared.frame.sequence
        primary = tuple(
            self.primary.detect(
                prepared.original, input_size=self.full_input_size
            )
        )
        supplemental = (
            tuple(
                self.supplementary.detect_evidence(
                    prepared.original, frame_sequence=sequence
                )
            )
            if self.supplementary is not None
            else ()
        )
        mapped = tuple(
            result
            for item in primary
            if (result := detection_to_violation(item, frame_sequence=sequence))
            is not None
        )
        return PrimaryDetection(
            primary=primary,
            supplementary=supplemental,
            evidence=mapped + supplemental,
        )
