"""NudeNet primary detector. Emits DetectionEvidence, not product Block."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from app.vision.detector import DetectionModel, Detector
from app.vision.detectors.base import DetectionEvidence, to_detection_evidence


class NudeNetPrimaryDetector:
    """Initialize NudeNet 640m with 320n fallback and standardize outputs."""

    def __init__(
        self,
        detector: Detector | None = None,
        *,
        model: DetectionModel | None = None,
        model_factory: Callable[..., DetectionModel] | None = None,
        model_path: str | Path | None = None,
    ) -> None:
        if detector is not None:
            self._detector = detector
        elif model_factory is not None:
            self._detector = Detector(
                model=model,
                model_factory=model_factory,
                model_path=model_path,
            )
        else:
            self._detector = Detector(model=model, model_path=model_path)
        self._last_raw: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        if self._detector.model_variant == "320n-fallback":
            return "nudenet_320n"
        return "nudenet_640m"

    @property
    def model_variant(self) -> str:
        return self._detector.model_variant

    @property
    def inference_resolution(self) -> int | None:
        return self._detector.inference_resolution

    @property
    def inner(self) -> Detector:
        return self._detector

    def detect(
        self,
        frame: np.ndarray,
        *,
        input_size: int,
    ) -> list[DetectionEvidence]:
        """Run NudeNet. ``input_size`` is recorded; NudeNet resizes internally."""

        del input_size
        if not isinstance(frame, np.ndarray):
            self._last_raw = []
            return []
        detections = list(self._detector.model.detect(frame))
        self._last_raw = detections
        return to_detection_evidence(detections, model=self.name)

    def check(self, image: np.ndarray) -> dict[str, Any]:
        """Compatibility wrapper used by DecisionEngine local recheck."""

        return self._detector.check(image)

    def last_raw_detections(self) -> list[dict[str, Any]]:
        return list(self._last_raw)
