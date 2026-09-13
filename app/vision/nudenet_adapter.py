"""Map NudeNet detections onto shared visual-violation evidence."""

from __future__ import annotations

from typing import Any

from app.vision.violation_policy import (
    ViolationEvidence,
    evidence_type_for_label,
)


def _bbox_from_detection(detection: dict[str, Any]) -> tuple[float, float, float, float] | None:
    box = detection.get("box")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x, y, width, height = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    return (x, y, width, height)


def detections_to_evidence(
    detections: list[dict[str, Any]],
    *,
    model: str = "nudenet",
    frame_sequence: int = 0,
) -> list[ViolationEvidence]:
    """Keep only NudeNet classes that map to a visual-violation type."""

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


class NudeNetAdapter:
    """Map NudeNet rows onto shared ViolationEvidence. No product Block rule."""

    def detect_evidence(
        self,
        detections: list[dict[str, Any]],
        *,
        frame_sequence: int = 0,
    ) -> list[ViolationEvidence]:
        return detections_to_evidence(
            detections,
            model="nudenet",
            frame_sequence=frame_sequence,
        )
