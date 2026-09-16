"""Primary-detector protocol. Adapters emit evidence, not product Block."""

from __future__ import annotations

from typing import Any, Protocol

from app.vision.preprocessor import PreparedFrame
from app.vision.violation_policy import (
    ViolationEvidence,
    evidence_type_for_label,
)

Box = tuple[float, float, float, float]


class PrimaryDetector(Protocol):
    """Run one local visual detector and return standardized evidence."""

    @property
    def name(self) -> str: ...

    def detect(
        self,
        prepared: PreparedFrame,
    ) -> tuple[ViolationEvidence, ...]: ...


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


def to_violation_evidence(
    detections: list[dict[str, Any]],
    *,
    model: str,
    frame_sequence: int,
) -> list[ViolationEvidence]:
    """Keep original labels; drop rows that are not visual-violation classes."""

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
                bbox=box_from_raw(detection.get("box")),
                model=str(detection.get("model") or model),
                frame_sequence=frame_sequence,
            )
        )
    return evidence
