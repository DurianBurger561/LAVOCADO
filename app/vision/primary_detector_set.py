"""Run enabled primary models and merge their typed visual evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter

from app.vision.detectors.base import PrimaryDetector
from app.vision.preprocessor import FramePreprocessor
from app.vision.regions import map_box_to_original
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


@dataclass(frozen=True, slots=True)
class DetectorLatency:
    preprocessing_ms: float = 0.0
    primary_ms: float = 0.0
    supplementary_ms: float = 0.0


class PrimaryDetectorSet:
    """Own model invocation, leaving thresholds to VisualDecisionEngine."""

    def __init__(
        self,
        primary: PrimaryDetector,
        *,
        supplementary: Yolo11Adapter | None = None,
        full_input_size: int,
    ) -> None:
        self.primary = primary
        self.supplementary = supplementary
        self.full_input_size = full_input_size
        self.last_latency = DetectorLatency()

    def detect(self, prepared: FramePreprocessor) -> PrimaryDetection:
        sequence = prepared.frame.sequence
        started = perf_counter()
        model_frame = prepared.prepare_full(self.full_input_size)
        model_image = model_frame.image
        preprocessing_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        primary = self.primary.detect(model_frame)
        primary_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        supplemental = (
            tuple(
                self.supplementary.detect_evidence(
                    model_image, frame_sequence=sequence
                )
            )
            if self.supplementary is not None
            else ()
        )
        self.last_latency = DetectorLatency(
            preprocessing_ms=preprocessing_ms,
            primary_ms=primary_ms,
            supplementary_ms=(perf_counter() - started) * 1000 if self.supplementary else 0.0,
        )
        return PrimaryDetection.from_primary(
            self.original_coordinates(prepared, model_image.shape, primary),
            supplementary=self.original_coordinates(
                prepared, model_image.shape, supplemental
            ),
        )

    @staticmethod
    def original_coordinates(
        prepared: FramePreprocessor,
        model_shape: tuple[int, ...],
        evidence: tuple[ViolationEvidence, ...],
    ) -> tuple[ViolationEvidence, ...]:
        """Keep public evidence boxes in full-resolution frame coordinates."""

        if model_shape[:2] == prepared.original.shape[:2]:
            return evidence
        mapped: list[ViolationEvidence] = []
        for item in evidence:
            if item.bbox is None:
                mapped.append(item)
                continue
            region = map_box_to_original(item.bbox, model_shape, prepared.original.shape)
            mapped.append(
                replace(
                    item,
                    bbox=(
                        None
                        if region is None
                        else (
                            float(region[0]),
                            float(region[1]),
                            float(region[2] - region[0]),
                            float(region[3] - region[1]),
                        )
                    ),
                )
            )
        return tuple(mapped)
