"""Central visual-violation mapping. Detectors do not own product rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ViolationEvidenceType(str, Enum):
    SEXUAL_ACT = "sexual_act"
    GENITAL_EXPOSURE = "genital_exposure"
    ANUS_EXPOSURE = "anus_exposure"
    BREAST_EXPOSURE = "breast_exposure"
    BUTTOCKS_EXPOSURE = "buttocks_exposure"


class VisualViolationClassification(str, Enum):
    VIOLATION = "violation"
    UNCERTAIN = "uncertain"
    CLEAR = "clear"


class DetectionTier(str, Enum):
    IGNORE = "ignore"
    PROPOSAL = "proposal"
    STRONG = "strong"


# Higher values are stronger product evidence. Sexual-act detections outrank
# isolated anatomy of similar confidence.
EVIDENCE_SEVERITY: dict[ViolationEvidenceType, int] = {
    ViolationEvidenceType.SEXUAL_ACT: 3,
    ViolationEvidenceType.GENITAL_EXPOSURE: 2,
    ViolationEvidenceType.ANUS_EXPOSURE: 2,
    ViolationEvidenceType.BREAST_EXPOSURE: 1,
    ViolationEvidenceType.BUTTOCKS_EXPOSURE: 1,
}

NUDENET_LABEL_TYPES: dict[str, ViolationEvidenceType] = {
    "FEMALE_GENITALIA_EXPOSED": ViolationEvidenceType.GENITAL_EXPOSURE,
    "MALE_GENITALIA_EXPOSED": ViolationEvidenceType.GENITAL_EXPOSURE,
    "ANUS_EXPOSED": ViolationEvidenceType.ANUS_EXPOSURE,
    "FEMALE_BREAST_EXPOSED": ViolationEvidenceType.BREAST_EXPOSURE,
    "BUTTOCKS_EXPOSED": ViolationEvidenceType.BUTTOCKS_EXPOSURE,
}

_YOLO_LABEL_TYPES: dict[str, ViolationEvidenceType] = {
    "sex": ViolationEvidenceType.SEXUAL_ACT,
    "sexual-act": ViolationEvidenceType.SEXUAL_ACT,
    "sexual-contact": ViolationEvidenceType.SEXUAL_ACT,
    "vaginal": ViolationEvidenceType.SEXUAL_ACT,
    "vaginal-sex": ViolationEvidenceType.SEXUAL_ACT,
    "anal": ViolationEvidenceType.SEXUAL_ACT,
    "anal-sex": ViolationEvidenceType.SEXUAL_ACT,
    "oral": ViolationEvidenceType.SEXUAL_ACT,
    "oral-sex": ViolationEvidenceType.SEXUAL_ACT,
    "blowjob": ViolationEvidenceType.SEXUAL_ACT,
    "handjob": ViolationEvidenceType.SEXUAL_ACT,
    "masturbation": ViolationEvidenceType.SEXUAL_ACT,
    "copulation": ViolationEvidenceType.SEXUAL_ACT,
    "penetration": ViolationEvidenceType.SEXUAL_ACT,
    "explicit-sex": ViolationEvidenceType.SEXUAL_ACT,
    "penis": ViolationEvidenceType.GENITAL_EXPOSURE,
    "vagina": ViolationEvidenceType.GENITAL_EXPOSURE,
    "vulva": ViolationEvidenceType.GENITAL_EXPOSURE,
    "female-genitalia": ViolationEvidenceType.GENITAL_EXPOSURE,
    "male-genitalia": ViolationEvidenceType.GENITAL_EXPOSURE,
    "female-genitalia-exposed": ViolationEvidenceType.GENITAL_EXPOSURE,
    "male-genitalia-exposed": ViolationEvidenceType.GENITAL_EXPOSURE,
    "genitalia": ViolationEvidenceType.GENITAL_EXPOSURE,
    "anus": ViolationEvidenceType.ANUS_EXPOSURE,
    "anus-exposed": ViolationEvidenceType.ANUS_EXPOSURE,
    "breast": ViolationEvidenceType.BREAST_EXPOSURE,
    "breasts": ViolationEvidenceType.BREAST_EXPOSURE,
    "female-breast": ViolationEvidenceType.BREAST_EXPOSURE,
    "female-breast-exposed": ViolationEvidenceType.BREAST_EXPOSURE,
    "nipple": ViolationEvidenceType.BREAST_EXPOSURE,
    "nipples": ViolationEvidenceType.BREAST_EXPOSURE,
    "buttocks": ViolationEvidenceType.BUTTOCKS_EXPOSURE,
    "buttock": ViolationEvidenceType.BUTTOCKS_EXPOSURE,
    "buttocks-exposed": ViolationEvidenceType.BUTTOCKS_EXPOSURE,
}

_ACTIVE_POLICY: ThresholdPolicy | None = None


@dataclass(frozen=True, slots=True)
class ThresholdPolicy:
    """Per-model proposal/strong tables. Numbers are experimental starting points."""

    tables: dict[str, dict[str, dict[str, float]]]

    @classmethod
    def from_settings(cls, settings: object | None = None) -> ThresholdPolicy:
        tables = {}
        raw = getattr(settings, "thresholds", None)
        if isinstance(raw, dict):
            tables = {
                "nudenet_640m": dict(raw.get("nudenet_640m") or {}),
                "yolo11_nsfw_small": dict(raw.get("yolo11_nsfw_small") or {}),
            }
        elif raw is not None:
            tables = {
                "nudenet_640m": dict(getattr(raw, "nudenet_640m", {}) or {}),
                "yolo11_nsfw_small": dict(getattr(raw, "yolo11_nsfw_small", {}) or {}),
            }
        if not tables.get("nudenet_640m") and not tables.get("yolo11_nsfw_small"):
            from app.settings.schema import default_threshold_tables

            defaults = default_threshold_tables()
            tables = {
                "nudenet_640m": dict(defaults.nudenet_640m),
                "yolo11_nsfw_small": dict(defaults.yolo11_nsfw_small),
            }
        return cls(tables=tables)

    def pair(
        self, label: str, model: str | None = None
    ) -> tuple[float, float] | None:
        key = _model_bucket(model)
        raw = str(label).strip()
        if key == "yolo11_nsfw_small":
            found = self._yolo_pair(raw)
            if found is not None:
                return found
        nudenet = self.tables.get("nudenet_640m") or {}
        if raw in nudenet:
            return _pair_from_dict(nudenet[raw])
        if key is None:
            found = self._yolo_pair(raw)
            if found is not None:
                return found
        return None

    def strong(self, label: str, model: str | None = None) -> float | None:
        pair = self.pair(label, model)
        return None if pair is None else pair[1]

    def proposal(self, label: str, model: str | None = None) -> float | None:
        pair = self.pair(label, model)
        return None if pair is None else pair[0]

    def tier(self, score: float, label: str, model: str | None = None) -> DetectionTier:
        pair = self.pair(label, model)
        if pair is None:
            return DetectionTier.IGNORE
        proposal, strong = pair
        if score >= strong:
            return DetectionTier.STRONG
        if score >= proposal:
            return DetectionTier.PROPOSAL
        return DetectionTier.IGNORE

    def _yolo_pair(self, label: str) -> tuple[float, float] | None:
        yolo = self.tables.get("yolo11_nsfw_small") or {}
        normalized = normalize_model_label(label)
        if normalized in yolo:
            return _pair_from_dict(yolo[normalized])
        if label in yolo:
            return _pair_from_dict(yolo[label])
        evidence_type = _YOLO_LABEL_TYPES.get(normalized)
        if evidence_type is None:
            return None
        canonical = {
            ViolationEvidenceType.SEXUAL_ACT: "sex",
            ViolationEvidenceType.GENITAL_EXPOSURE: (
                "vagina"
                if "female" in normalized or "vagin" in normalized
                else "vulva" if "vulva" in normalized else "penis"
            ),
            ViolationEvidenceType.ANUS_EXPOSURE: "anus",
            ViolationEvidenceType.BREAST_EXPOSURE: "breast",
            ViolationEvidenceType.BUTTOCKS_EXPOSURE: "buttocks",
        }[evidence_type]
        if canonical in yolo:
            return _pair_from_dict(yolo[canonical])
        return None


def _model_bucket(model: str | None) -> str | None:
    raw = str(model or "").strip().lower().replace("-", "_")
    if raw.startswith("yolo"):
        return "yolo11_nsfw_small"
    if raw.startswith("nudenet") or raw in {"injected", "640m", "320n_fallback", "320n-fallback"}:
        return "nudenet_640m"
    return None


def _pair_from_dict(payload: object) -> tuple[float, float] | None:
    if not isinstance(payload, dict):
        return None
    try:
        proposal = float(payload.get("proposal"))
        strong = float(payload.get("strong"))
    except (TypeError, ValueError):
        return None
    return (proposal, strong)


def activate_threshold_policy(policy: ThresholdPolicy | None) -> None:
    global _ACTIVE_POLICY
    _ACTIVE_POLICY = policy


def active_threshold_policy() -> ThresholdPolicy:
    return _ACTIVE_POLICY or ThresholdPolicy.from_settings()


@dataclass(frozen=True, slots=True)
class ViolationEvidence:
    evidence_type: ViolationEvidenceType
    label: str
    confidence: float
    bbox: tuple[float, float, float, float] | None
    model: str
    frame_sequence: int


@dataclass(frozen=True, slots=True)
class VisualViolationDecision:
    classification: VisualViolationClassification
    evidence: tuple[ViolationEvidence, ...]
    reason_codes: tuple[str, ...]
    primary_region: tuple[int, int, int, int] | None
    frame_sequence: int
    evidence_type: ViolationEvidenceType | None = None
    label: str | None = None
    confidence: float = 0.0
    track_id: int | None = None
    track_evidence: float | None = None
    track_fresh_hits: int = 0
    monitor_index: int = 1
    scan_mode: str | None = None
    scan_interval_ms: float | None = None
    context_label: str | None = None
    context_score: float | None = None
    rescue_tile_index: int | None = None
    threshold: float | None = None
    shadow: dict[str, Any] | None = None


def normalize_model_label(label: str) -> str:
    return "-".join(str(label).strip().lower().replace("_", " ").split())


def evidence_type_for_label(label: str) -> ViolationEvidenceType | None:
    raw = str(label).strip()
    if raw in NUDENET_LABEL_TYPES:
        return NUDENET_LABEL_TYPES[raw]
    return _YOLO_LABEL_TYPES.get(normalize_model_label(raw))


def threshold_for_label(label: str, model: str | None = None) -> float | None:
    return active_threshold_policy().strong(label, model)


def severity_for(evidence_type: ViolationEvidenceType) -> int:
    return EVIDENCE_SEVERITY[evidence_type]


def is_borderline_score(score: float, threshold: float, margin: float) -> bool:
    return threshold - margin <= score < threshold


def proposal_threshold_for_label(
    label: str,
    margin: float,
    model: str | None = None,
) -> float | None:
    policy = _ACTIVE_POLICY
    if policy is not None:
        proposal = policy.proposal(label, model)
        if proposal is not None:
            return proposal
    strong = threshold_for_label(label, model)
    if strong is None:
        return None
    return max(0.0, float(strong) - float(margin))


def tier_for_score(
    score: float,
    label: str,
    *,
    margin: float,
    model: str | None = None,
) -> DetectionTier:
    policy = _ACTIVE_POLICY
    if policy is not None:
        pair = policy.pair(label, model)
        if pair is not None:
            return policy.tier(score, label, model)
    strong = threshold_for_label(label, model)
    if strong is None:
        return DetectionTier.IGNORE
    if score >= strong:
        return DetectionTier.STRONG
    if score >= max(0.0, strong - margin):
        return DetectionTier.PROPOSAL
    return DetectionTier.IGNORE


def strongest_evidence(
    evidence: list[ViolationEvidence],
) -> ViolationEvidence | None:
    if not evidence:
        return None
    return max(
        evidence,
        key=lambda item: (
            severity_for(item.evidence_type),
            item.confidence,
        ),
    )


def evidence_to_dict(item: ViolationEvidence) -> dict[str, Any]:
    return {
        "evidence_type": item.evidence_type.value,
        "label": item.label,
        "confidence": item.confidence,
        "bbox": None if item.bbox is None else list(item.bbox),
        "model": item.model,
        "frame_sequence": item.frame_sequence,
    }
