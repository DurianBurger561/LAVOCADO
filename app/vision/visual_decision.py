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


@dataclass(frozen=True, slots=True)
class PrimaryAssessment:
    classification: VisualViolationClassification
    strong: ViolationEvidence | None
    threshold: float | None


@dataclass(frozen=True, slots=True)
class BorderlineCandidate:
    evidence: ViolationEvidence
    threshold: float


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

    def assess_primary(
        self, evidence: Iterable[ViolationEvidence]
    ) -> PrimaryAssessment:
        """Choose the highest-confidence strong primary hit under this policy."""

        strong = [
            (item, threshold)
            for item in evidence
            if (threshold := self.threshold_policy.strong(item.label, item.model))
            is not None
            and item.confidence >= threshold
        ]
        if not strong:
            return PrimaryAssessment(VisualViolationClassification.CLEAR, None, None)
        strongest, threshold = max(strong, key=lambda pair: pair[0].confidence)
        return PrimaryAssessment(
            VisualViolationClassification.VIOLATION, strongest, threshold
        )

    def borderline_candidate(
        self, evidence: Iterable[ViolationEvidence]
    ) -> BorderlineCandidate | None:
        """Select a typed proposal, including the configured borderline band."""

        candidates: list[BorderlineCandidate] = []
        for item in evidence:
            threshold = self.threshold_policy.strong(item.label, item.model)
            if threshold is not None and (
                self.threshold_policy.tier(item.confidence, item.label, item.model)
                is DetectionTier.PROPOSAL
                or is_borderline_score(
                    item.confidence, threshold, self.borderline_margin
                )
            ):
                candidates.append(BorderlineCandidate(item, threshold))
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item.evidence.confidence - item.threshold,
                item.evidence.confidence,
            ),
        )

    @staticmethod
    def finalize(
        payload: Mapping[str, Any], *, frame_sequence: int, monitor_index: int
    ) -> VisualViolationDecision:
        return visual_decision_from_engine_payload(
            dict(payload), frame_sequence=frame_sequence, monitor_index=monitor_index
        )
