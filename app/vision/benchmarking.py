"""Keep Vision Benchmark and Full Pipeline Benchmark as separate labs."""

from __future__ import annotations

from typing import Any

from app.context.models import ContextPolicyAction
from app.context.policy.resolver import resolve_context_policy
from app.settings.schema import TemporalSettings
from app.vision.nudenet_adapter import detections_to_evidence
from app.vision.temporal import TemporalVerifier
from app.vision.violation_policy import (
    VisualViolationClassification,
    evidence_to_dict,
    strongest_evidence,
    threshold_for_label,
)

SCENARIO_TAGS = frozenset({"medical", "education", "art", "news"})
VISION_GROUND_TRUTH_NOTE = "Visual Policy Ground Truth"


def normalize_scenario_tag(tag: str | None) -> str | None:
    """Store scenario metadata. Tags never change Vision ground truth."""

    if tag is None:
        return None
    value = str(tag).strip().lower()
    return value or None


def detector_evidence_payload(
    detections: list[dict[str, Any]] | None,
    *,
    model: str = "nudenet",
) -> list[dict[str, Any]]:
    """Return label/type/confidence only; never boxes or pixels."""

    if not detections:
        return []
    payload: list[dict[str, Any]] = []
    for item in detections_to_evidence(detections, model=model):
        row = evidence_to_dict(item)
        row.pop("bbox", None)
        payload.append(row)
    return payload


def vision_ground_truth(
    detections: list[dict[str, Any]],
    *,
    scenario_tag: str | None = None,
) -> str:
    """Label an image using Visual Violation Policy only.

    ``scenario_tag`` values such as Medical / Art / Education / News are
    metadata. They never force Allow. Explicit anatomy is a true positive.
    """

    del scenario_tag
    evidence = detections_to_evidence(detections, model="nudenet")
    strong = [
        item
        for item in evidence
        if (threshold := threshold_for_label(item.label)) is not None
        and item.confidence >= threshold
    ]
    if strongest_evidence(strong) is None:
        return VisualViolationClassification.CLEAR.value
    return VisualViolationClassification.VIOLATION.value


def evaluate_full_pipeline(
    *,
    app_action: ContextPolicyAction,
    website_action: ContextPolicyAction | None,
    vision_result: dict[str, Any] | None = None,
    temporal_confirmed: bool = False,
    detections: list[dict[str, Any]] | None = None,
    temporal_history: tuple[bool, ...] | None = None,
    scenario_tag: str | None = None,
) -> dict[str, Any]:
    """Simulate Context Policy + optional Vision + Protection."""

    tag = normalize_scenario_tag(scenario_tag)
    policy = resolve_context_policy(app_action, website_action)
    app_rule = app_action.value
    website_rule = (
        ContextPolicyAction.NORMAL.value
        if website_action is None
        else website_action.value
    )
    if policy is ContextPolicyAction.FORCE_BLOCK:
        return _pipeline_record(
            policy=policy.value,
            app_rule=app_rule,
            website_rule=website_rule,
            vision_called=False,
            classification=None,
            protection=True,
            reason="force_block",
            detections=None,
            temporal_history=(),
            scenario_tag=tag,
        )
    if policy is ContextPolicyAction.FULL_BYPASS:
        return _pipeline_record(
            policy=policy.value,
            app_rule=app_rule,
            website_rule=website_rule,
            vision_called=False,
            classification=None,
            protection=False,
            reason="full_bypass",
            detections=None,
            temporal_history=(),
            scenario_tag=tag,
        )

    result = vision_result or {}
    classification = result.get("classification")
    if classification is None and detections is not None:
        classification = vision_ground_truth(detections, scenario_tag=tag)
    history = temporal_history
    if history is None:
        history = (True,) if temporal_confirmed else ()
    return _pipeline_record(
        policy=policy.value,
        app_rule=app_rule,
        website_rule=website_rule,
        vision_called=True,
        classification=None if classification is None else str(classification),
        protection=bool(temporal_confirmed),
        reason="normal_vision",
        detections=detections,
        temporal_history=history,
        scenario_tag=tag,
    )


def evaluate_product_pipeline(
    *,
    app_action: ContextPolicyAction,
    website_action: ContextPolicyAction | None,
    vision_frames: list[str] | None = None,
    detections: list[dict[str, Any]] | None = None,
    scenario_tag: str | None = None,
    window_size: int = TemporalSettings().window_size,
    required_hits: int = TemporalSettings().min_fresh_hits,
) -> dict[str, Any]:
    """Full Product Benchmark: Context Policy + Vision + Temporal + Protection.

    A single visual violation is not enough. Protection requires confirmed
    visual violations on distinct fresh frames. UNCERTAIN requests focused
    verification and does not count as a temporal hit.
    """

    tag = normalize_scenario_tag(scenario_tag)
    policy = resolve_context_policy(app_action, website_action)
    app_rule = app_action.value
    website_rule = (
        ContextPolicyAction.NORMAL.value
        if website_action is None
        else website_action.value
    )
    if policy is ContextPolicyAction.FORCE_BLOCK:
        return _pipeline_record(
            policy=policy.value,
            app_rule=app_rule,
            website_rule=website_rule,
            vision_called=False,
            classification=None,
            protection=True,
            reason="force_block",
            detections=None,
            temporal_history=(),
            scenario_tag=tag,
            focused_verification=False,
        )
    if policy is ContextPolicyAction.FULL_BYPASS:
        return _pipeline_record(
            policy=policy.value,
            app_rule=app_rule,
            website_rule=website_rule,
            vision_called=False,
            classification=None,
            protection=False,
            reason="full_bypass",
            detections=None,
            temporal_history=(),
            scenario_tag=tag,
            focused_verification=False,
        )

    verifier = TemporalVerifier(window_size, required_hits)
    focused = False
    last_classification: str | None = None
    last_violation: str | None = None
    protection = False
    for sequence, raw in enumerate(vision_frames or (), start=1):
        classification = VisualViolationClassification(str(raw).strip().lower())
        last_classification = classification.value
        if classification is VisualViolationClassification.VIOLATION:
            last_violation = classification.value
            protection = verifier.update(True, frame_sequence=sequence) or protection
        elif classification is VisualViolationClassification.UNCERTAIN:
            focused = True
            protection = verifier.update(False, frame_sequence=sequence) or protection
        else:
            protection = verifier.update(False, frame_sequence=sequence) or protection
        if protection:
            break
    if last_classification is None and detections is not None:
        last_classification = vision_ground_truth(detections, scenario_tag=tag)
    last_classification = last_violation or last_classification
    return _pipeline_record(
        policy=policy.value,
        app_rule=app_rule,
        website_rule=website_rule,
        vision_called=True,
        classification=last_classification,
        protection=protection,
        reason="normal_temporal",
        detections=detections,
        temporal_history=verifier.history,
        scenario_tag=tag,
        focused_verification=focused,
    )


def score_scenario(result: dict[str, Any]) -> str:
    """Interpret a tagged case without treating medical anatomy as a FP."""

    tag = result.get("scenario_tag")
    if tag not in SCENARIO_TAGS:
        return "untagged"
    if result.get("policy") == ContextPolicyAction.FULL_BYPASS.value:
        if result.get("vision_called") or result.get("protection"):
            return "whitelist_incorrect"
        return "whitelist_correct"
    if result.get("policy") == ContextPolicyAction.FORCE_BLOCK.value:
        return "blacklist"
    if result.get("classification") == VisualViolationClassification.VIOLATION.value:
        return "visual_true_positive"
    return "normal"


def format_failure_explorer(result: dict[str, Any]) -> str:
    explorer = result.get("explorer")
    if not isinstance(explorer, dict):
        explorer = {}
    evidence = explorer.get("detector_evidence") or []
    evidence_text = ",".join(
        str(item.get("label"))
        for item in evidence
        if isinstance(item, dict) and item.get("label")
    ) or "none"
    temporal = explorer.get("temporal_state") or []
    return (
        f"context_policy={explorer.get('context_policy')} "
        f"app_rule={explorer.get('app_rule')} "
        f"website_rule={explorer.get('website_rule')} "
        f"vision_called={explorer.get('vision_called')} "
        f"detector_evidence={evidence_text} "
        f"temporal_state={list(temporal)} "
        f"final_action={explorer.get('final_action')} "
        f"scenario_tag={explorer.get('scenario_tag') or 'none'} "
        f"scenario_score={result.get('scenario_score')}"
    )


def _pipeline_record(
    *,
    policy: str,
    app_rule: str,
    website_rule: str,
    vision_called: bool,
    classification: str | None,
    protection: bool,
    reason: str,
    detections: list[dict[str, Any]] | None,
    temporal_history: tuple[bool, ...],
    scenario_tag: str | None,
    focused_verification: bool = False,
) -> dict[str, Any]:
    evidence = detector_evidence_payload(detections) if vision_called else []
    record = {
        "policy": policy,
        "vision_called": vision_called,
        "classification": classification,
        "protection": protection,
        "reason": reason,
        "scenario_tag": scenario_tag,
        "focused_verification": focused_verification,
        "explorer": {
            "context_policy": policy,
            "app_rule": app_rule,
            "website_rule": website_rule,
            "vision_called": vision_called,
            "detector_evidence": evidence,
            "temporal_state": [int(value) for value in temporal_history],
            "final_action": "protect" if protection else "allow",
            "scenario_tag": scenario_tag,
            "classification": classification,
            "focused_verification": focused_verification,
            "ground_truth_kind": (
                VISION_GROUND_TRUTH_NOTE if vision_called else None
            ),
        },
    }
    record["scenario_score"] = score_scenario(record)
    return record
