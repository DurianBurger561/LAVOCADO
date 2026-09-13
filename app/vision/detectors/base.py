"""Primary-detector protocol. Adapters emit evidence, not product Block."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from app.vision.violation_policy import (
    ViolationEvidence,
    evidence_to_dict,
    evidence_type_for_label,
    threshold_for_label,
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


def check_result_from_evidence(
    evidence: list[DetectionEvidence],
    *,
    raw_detections: list[dict[str, Any]] | None = None,
    frame_sequence: int = 0,
) -> dict[str, Any]:
    """Apply per-label strong thresholds. Adapters must not call this internally
    except through a compatibility ``check()`` wrapper used by DecisionEngine.
    """

    checkpoints = raw_detections if isinstance(raw_detections, list) else [
        {
            "class": item.label,
            "score": item.confidence,
            "box": None if item.box is None else list(item.box),
        }
        for item in evidence
    ]
    violation_payload = []
    for item in evidence:
        mapped = detection_to_violation(item, frame_sequence=frame_sequence)
        if mapped is not None:
            violation_payload.append(evidence_to_dict(mapped))

    blocking: list[tuple[DetectionEvidence, float]] = []
    for item in evidence:
        threshold = threshold_for_label(item.label)
        if threshold is not None and item.confidence >= threshold:
            blocking.append((item, threshold))

    if not blocking:
        return {
            "blocked": False,
            "reason": "",
            "label": None,
            "confidence": 0.0,
            "box": None,
            "check_points": checkpoints,
            "evidence": violation_payload,
        }

    strongest, threshold = max(blocking, key=lambda pair: pair[0].confidence)
    return {
        "blocked": True,
        "reason": (
            f"{strongest.label} "
            f"(score {strongest.confidence:.2f}, threshold {threshold:.2f})"
        ),
        "label": strongest.label,
        "confidence": strongest.confidence,
        "box": None if strongest.box is None else list(strongest.box),
        "check_points": checkpoints,
        "evidence": violation_payload,
    }
