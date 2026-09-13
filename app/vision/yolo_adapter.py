"""Optional YOLO11 adapter. Maps anatomy and sexual-act labels to evidence."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from app import config
from app.vision.violation_policy import (
    ViolationEvidence,
    evidence_type_for_label,
)

LOGGER = logging.getLogger(__name__)


class YoloDetectionModel(Protocol):
    """Minimal detect() interface used by the adapter and tests."""

    def detect(self, image: np.ndarray) -> list[dict[str, Any]]:
        ...


def _bbox_from_detection(detection: dict[str, Any]) -> tuple[float, float, float, float] | None:
    box = detection.get("box")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        values = tuple(float(value) for value in box)
    except (TypeError, ValueError):
        return None
    return values


def detections_to_evidence(
    detections: list[dict[str, Any]],
    *,
    model: str = "yolo11",
    frame_sequence: int = 0,
) -> list[ViolationEvidence]:
    """Convert YOLO-style {class, score, box} rows into violation evidence."""

    evidence: list[ViolationEvidence] = []
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        label = str(detection.get("class", "")).strip()
        evidence_type = evidence_type_for_label(label)
        if evidence_type is None:
            continue
        try:
            confidence = float(detection.get("score", 0.0))
        except (TypeError, ValueError):
            continue
        evidence.append(
            ViolationEvidence(
                evidence_type=evidence_type,
                label=label,
                confidence=max(0.0, min(1.0, confidence)),
                bbox=_bbox_from_detection(detection),
                model=model,
                frame_sequence=frame_sequence,
            )
        )
    return evidence


class Yolo11Adapter:
    """Run an injected YOLO detector and emit unified ViolationEvidence."""

    def __init__(
        self,
        model: YoloDetectionModel,
        *,
        model_name: str = "yolo11",
    ) -> None:
        self.model = model
        self.model_name = model_name

    def detect_evidence(
        self,
        image: np.ndarray,
        *,
        frame_sequence: int = 0,
    ) -> list[ViolationEvidence]:
        if not isinstance(image, np.ndarray):
            return []
        try:
            detections = list(self.model.detect(image))
        except Exception:
            LOGGER.exception("YOLO11 inference failed; ignoring YOLO evidence")
            return []
        return detections_to_evidence(
            detections,
            model=self.model_name,
            frame_sequence=frame_sequence,
        )


def load_yolo_adapter(
    *,
    enabled: bool | None = None,
    model_factory: Callable[[], YoloDetectionModel] | None = None,
) -> Yolo11Adapter | None:
    """Load an optional local YOLO model. Missing deps never crash protection."""

    if enabled is None:
        enabled = config.YOLO_ENABLED
    if not enabled:
        LOGGER.info("YOLO11 adapter is disabled")
        return None
    if model_factory is None:
        LOGGER.info("YOLO11 adapter has no injected model; continuing without it")
        return None
    try:
        return Yolo11Adapter(model_factory())
    except Exception:
        LOGGER.exception("YOLO11 adapter is unavailable; continuing without it")
        return None
