"""Pure visual evidence assessment with no capture or model dependencies."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.vision.violation_policy import (
    DetectionTier,
    ThresholdPolicy,
    ViolationEvidence,
    VisualViolationClassification,
    VisualViolationDecision,
    evidence_type_for_label,
    is_borderline_score,
    strongest_evidence,
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


@dataclass(slots=True)
class VisualDecisionDraft:
    """Typed, per-frame orchestration state; never a JSON/IPC payload."""

    classification: VisualViolationClassification
    evidence: tuple[ViolationEvidence, ...]
    source: str = ""
    label: str | None = None
    confidence: float = 0.0
    box: tuple[float, float, float, float] | None = None
    region: tuple[int, int, int, int] | None = None
    threshold: float | None = None
    context_label: str | None = None
    context_score: float | None = None
    rescue_tile_index: int | None = None
    recheck_performed: bool = False
    track_id: int | None = None
    track_evidence: float | None = None
    track_fresh_hits: int = 0
    scan_mode: str | None = None
    scan_interval_ms: float | None = None


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
        draft: VisualDecisionDraft, *, frame_sequence: int, monitor_index: int
    ) -> VisualViolationDecision:
        if not isinstance(draft, VisualDecisionDraft):
            raise TypeError("Vision decision draft must be typed")
        if not isinstance(draft.classification, VisualViolationClassification):
            raise TypeError("Vision decision classification must be typed")
        if not isinstance(draft.evidence, tuple) or not all(
            isinstance(item, ViolationEvidence) for item in draft.evidence
        ):
            raise TypeError("Vision evidence must remain typed")
        return VisualViolationDecision(
            classification=draft.classification,
            evidence=draft.evidence,
            evidence_type=(
                evidence_type_for_label(draft.label)
                if draft.classification is VisualViolationClassification.VIOLATION
                and draft.label is not None
                else None
            ),
            reason_codes=(draft.source,) if draft.source else (),
            primary_region=draft.region,
            frame_sequence=frame_sequence,
            label=draft.label,
            confidence=draft.confidence,
            track_id=draft.track_id,
            track_evidence=draft.track_evidence,
            track_fresh_hits=draft.track_fresh_hits,
            monitor_index=monitor_index,
            scan_mode=draft.scan_mode,
            scan_interval_ms=draft.scan_interval_ms,
            context_label=draft.context_label,
            context_score=draft.context_score,
            rescue_tile_index=draft.rescue_tile_index,
            threshold=draft.threshold,
        )
