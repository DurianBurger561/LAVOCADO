"""Pure visual evidence assessment with no capture or model dependencies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.vision.violation_policy import (
    DetectionTier,
    ThresholdPolicy,
    ViolationEvidence,
    VisualViolationClassification,
    VisualViolationDecision,
    is_borderline_score,
    strongest_evidence,
    visual_decision_from_engine_payload,
)


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    classification: VisualViolationClassification
    strong: ViolationEvidence | None
    proposal: ViolationEvidence | None


class VisualDecisionEngine:
    """Classify typed evidence without running inference or changing state."""

    def __init__(
        self, threshold_policy: ThresholdPolicy, *, borderline_margin: float = 0.0
    ) -> None:
        self.threshold_policy = threshold_policy
        self.borderline_margin = borderline_margin

    def assess(self, evidence: Iterable[ViolationEvidence]) -> EvidenceAssessment:
        strong: list[ViolationEvidence] = []
        proposal: list[ViolationEvidence] = []
        for item in evidence:
            tier = self.threshold_policy.tier(
                item.confidence, item.label, item.model
            )
            if tier is DetectionTier.STRONG:
                strong.append(item)
            elif tier is DetectionTier.PROPOSAL:
                proposal.append(item)
        classification = (
            VisualViolationClassification.VIOLATION
            if strong
            else VisualViolationClassification.UNCERTAIN
            if proposal
            else VisualViolationClassification.CLEAR
        )
        return EvidenceAssessment(
            classification=classification,
            strong=strongest_evidence(strong),
            proposal=strongest_evidence(proposal),
        )

    def borderline_detection(
        self, detections: object
    ) -> dict[str, Any] | None:
        """Select an unconfirmed proposal from raw detector rows."""

        if not isinstance(detections, list):
            return None
        candidates: list[dict[str, Any]] = []
        for detection in detections:
            if not isinstance(detection, dict):
                continue
            label = str(detection.get("class", ""))
            score = float(detection.get("score", 0.0))
            model = detection.get("model")
            model_name = None if model is None else str(model)
            threshold = self.threshold_policy.strong(label, model_name)
            if threshold is not None and (
                self.threshold_policy.tier(score, label, model_name)
                is DetectionTier.PROPOSAL
                or is_borderline_score(score, threshold, self.borderline_margin)
            ):
                candidate = dict(detection)
                candidate["threshold"] = threshold
                candidates.append(candidate)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                float(item["score"]) - float(item["threshold"]),
                float(item["score"]),
            ),
        )

    @staticmethod
    def finalize(
        payload: Mapping[str, Any], *, frame_sequence: int, monitor_index: int
    ) -> VisualViolationDecision:
        return visual_decision_from_engine_payload(
            dict(payload), frame_sequence=frame_sequence, monitor_index=monitor_index
        )
