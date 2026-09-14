"""Primary-detector protocol. Adapters emit evidence, not product Block."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from app.vision.violation_policy import (
    ViolationEvidence,
    evidence_type_for_label,
)

Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class DetectionEvidence:
    """Normalized detector output. Never includes a product decision."""

    label: str
    confidence: float
    box: Box | None
    model: str


class PrimaryDetector(Protocol):
    """Run one local visual detector and return standardized evidence."""

    @property
    def name(self) -> str: ...

    def detect(
        self,
        frame: np.ndarray,
        *,
        input_size: int,
    ) -> list[DetectionEvidence]: ...


def box_from_raw(box: object) -> Box | None:
    """Accept XYWH boxes from NudeNet/YOLO adapters."""

    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x, y, width, height = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (x, y, width, height)


def to_detection_evidence(
    detections: list[dict[str, Any]],
    *,
    model: str,
) -> list[DetectionEvidence]:
    """Keep original labels; drop rows that are not visual-violation classes."""

    evidence: list[DetectionEvidence] = []
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        label = str(detection.get("class", "")).strip()
        if evidence_type_for_label(label) is None:
            continue
        try:
            confidence = float(detection.get("score", 0.0))
        except (TypeError, ValueError):
            continue
        evidence.append(
            DetectionEvidence(
                label=label,
                confidence=max(0.0, min(1.0, confidence)),
                box=box_from_raw(detection.get("box")),
                model=model,
            )
        )
    return evidence


def detection_to_violation(
    item: DetectionEvidence,
    *,
    frame_sequence: int = 0,
) -> ViolationEvidence | None:
    evidence_type = evidence_type_for_label(item.label)
    if evidence_type is None:
        return None
    return ViolationEvidence(
        evidence_type=evidence_type,
        label=item.label,
        confidence=item.confidence,
        bbox=item.box,
        model=item.model,
        frame_sequence=frame_sequence,
    )
