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

YOLO_DEFAULT_THRESHOLDS: dict[ViolationEvidenceType, float] = {
    ViolationEvidenceType.SEXUAL_ACT: 0.45,
    ViolationEvidenceType.GENITAL_EXPOSURE: 0.45,
    ViolationEvidenceType.ANUS_EXPOSURE: 0.50,
    ViolationEvidenceType.BREAST_EXPOSURE: 0.65,
    ViolationEvidenceType.BUTTOCKS_EXPOSURE: 0.70,
}


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
    source: str
    label: str | None = None
    confidence: float = 0.0

    @property
    def blocked(self) -> bool:
        return self.classification is VisualViolationClassification.VIOLATION


def normalize_model_label(label: str) -> str:
    return "-".join(str(label).strip().lower().replace("_", " ").split())


def evidence_type_for_label(label: str) -> ViolationEvidenceType | None:
    raw = str(label).strip()
    if raw in NUDENET_LABEL_TYPES:
        return NUDENET_LABEL_TYPES[raw]
    return _YOLO_LABEL_TYPES.get(normalize_model_label(raw))


def threshold_for_label(label: str) -> float | None:
    from app import config

    raw = str(label).strip()
    if raw in config.BLOCK_THRESHOLDS:
        return float(config.BLOCK_THRESHOLDS[raw])
    evidence_type = evidence_type_for_label(raw)
    if evidence_type is None:
        return None
    return YOLO_DEFAULT_THRESHOLDS[evidence_type]


def severity_for(evidence_type: ViolationEvidenceType) -> int:
    return EVIDENCE_SEVERITY[evidence_type]


def is_borderline_score(score: float, threshold: float, margin: float) -> bool:
    return threshold - margin <= score < threshold


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
