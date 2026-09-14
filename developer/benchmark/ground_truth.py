"""Visual-policy labels for standalone detector diagnostics."""

from __future__ import annotations

from typing import Any

from app.vision.detectors.base import to_violation_evidence
from app.vision.violation_policy import (
    VisualViolationClassification,
    strongest_evidence,
    threshold_for_label,
)

VISION_GROUND_TRUTH_NOTE = "Visual Policy Ground Truth"


def visual_policy_classification(
    detections: list[dict[str, Any]],
) -> VisualViolationClassification:
    """Classify detector rows with the current visual threshold policy only."""

    evidence = to_violation_evidence(
        detections,
        model="nudenet",
        frame_sequence=1,
    )
    strong = [
        item
        for item in evidence
        if (threshold := threshold_for_label(item.label)) is not None
        and item.confidence >= threshold
    ]
    return (
        VisualViolationClassification.CLEAR
        if strongest_evidence(strong) is None
        else VisualViolationClassification.VIOLATION
    )
