"""Map detector confidence onto track evidence. Same-frame rechecks do not add hits."""

from __future__ import annotations

from app.vision.violation_policy import threshold_for_label

PROPOSAL_EVIDENCE = 0.6
STRONG_EVIDENCE = 1.2


def evidence_from_confidence(
    confidence: float,
    label: str | None,
    *,
    proposal_weight: float = PROPOSAL_EVIDENCE,
    strong_weight: float = STRONG_EVIDENCE,
) -> float:
    """Strong detections contribute more evidence than proposal-level scores."""

    if label is None:
        return 0.0
    threshold = threshold_for_label(label)
    if threshold is None:
        return 0.0
    score = max(0.0, float(confidence))
    if score >= threshold:
        extra = min(1.0, (score - threshold) / max(1e-6, 1.0 - threshold))
        return strong_weight + extra * 0.4
    return proposal_weight * min(1.0, score / max(threshold, 1e-6))


def decay_evidence(score: float, decay: float) -> float:
    return max(0.0, float(score) * float(decay))


def is_confirmed(
    *,
    fresh_hits: int,
    evidence_score: float,
    min_fresh_hits: int,
    evidence_threshold: float,
    window_hits: int | None = None,
    required_window_hits: int | None = None,
    window_full: bool = True,
    confirmation: str = "boolean",
) -> bool:
    """Boolean 2/3, evidence score, or both. Modes stay selectable."""

    mode = str(confirmation or "boolean").strip().lower()
    if mode not in {"boolean", "evidence", "both"}:
        mode = "boolean"
    hits_ok = fresh_hits >= min_fresh_hits
    if (
        window_hits is not None
        and required_window_hits is not None
        and window_hits < required_window_hits
    ):
        hits_ok = False
    boolean_ok = hits_ok and window_full
    evidence_ok = float(evidence_score) >= float(evidence_threshold)
    if mode == "evidence":
        return hits_ok and evidence_ok
    if mode == "both":
        return boolean_ok and evidence_ok
    return boolean_ok
