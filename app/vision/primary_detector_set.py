"""Run enabled primary models and merge their typed visual evidence."""

from __future__ import annotations

from dataclasses import dataclass

from app.vision.detectors.base import PrimaryDetector
from app.vision.preprocessor import FramePreprocessor
from app.vision.violation_policy import ViolationEvidence
from app.vision.yolo_adapter import Yolo11Adapter


@dataclass(frozen=True, slots=True)
class PrimaryDetection:
    """One inference result; no classification or protection action."""

    primary: tuple[ViolationEvidence, ...]
    supplementary: tuple[ViolationEvidence, ...]
    evidence: tuple[ViolationEvidence, ...]

    @classmethod
    def from_primary(
        cls,
        primary: tuple[ViolationEvidence, ...],
        *,
        supplementary: tuple[ViolationEvidence, ...] = (),
    ) -> PrimaryDetection:
        return cls(primary, supplementary, primary + supplementary)


class PrimaryDetectorSet:
    """Own model invocation, leaving thresholds to VisualDecisionEngine."""

    def __init__(
        self,
        primary: PrimaryDetector,
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
                prepared.original, input_size=self.full_input_size, frame_sequence=sequence
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
        return PrimaryDetection.from_primary(
            primary, supplementary=supplemental
        )
