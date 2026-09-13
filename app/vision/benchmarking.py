"""Pure helpers that keep Vision Benchmark and Full Pipeline Benchmark apart."""

from __future__ import annotations

from typing import Any

from app.context.models import ContextPolicyAction
from app.context.policy.resolver import resolve_context_policy
from app.vision.nudenet_adapter import detections_to_evidence
from app.vision.violation_policy import (
    VisualViolationClassification,
    strongest_evidence,
    threshold_for_label,
)


def vision_ground_truth(detections: list[dict[str, Any]]) -> str:
    """Label an image using Visual Violation Policy only.

    Scenario tags such as Medical / Art / Education are metadata. They never
    force Allow. Explicit anatomy is a true positive for this benchmark.
    """

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
) -> dict[str, Any]:
    """Simulate Context Policy + optional Vision + Protection."""

    policy = resolve_context_policy(app_action, website_action)
    if policy is ContextPolicyAction.FORCE_BLOCK:
        return {
            "policy": policy.value,
            "vision_called": False,
            "classification": None,
            "protection": True,
            "reason": "force_block",
        }
    if policy is ContextPolicyAction.FULL_BYPASS:
        return {
            "policy": policy.value,
            "vision_called": False,
            "classification": None,
            "protection": False,
            "reason": "full_bypass",
        }

    result = vision_result or {}
    return {
        "policy": policy.value,
        "vision_called": True,
        "classification": result.get("classification"),
        "protection": bool(temporal_confirmed),
        "reason": "normal_vision",
    }
