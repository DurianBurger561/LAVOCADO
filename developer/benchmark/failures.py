"""One privacy-safe failure classification for every Benchmark Lab surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureKind(str, Enum):
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"
    CONTEXT_CONFLICT = "context_conflict"
    TEMPORAL_MISS = "temporal_miss"
    CAPTURE_FAILURE = "capture_failure"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class FailureCase:
    sample_id: str
    config_id: str
    kind: FailureKind

    def to_dict(self) -> dict[str, str]:
        return {
            "sample_id": self.sample_id,
            "config_id": self.config_id,
            "kind": self.kind.value,
        }


def failure_from_row(row: Mapping[str, Any]) -> FailureCase | None:
    """Classify stored scalar results without loading sample pixels."""

    outcome = str(row.get("outcome") or "").lower()
    error = str(row.get("error") or "").lower()
    if outcome == "timeout" or "timeout" in error:
        kind = FailureKind.TIMEOUT
    elif outcome == "capture_failure" or "capture" in error:
        kind = FailureKind.CAPTURE_FAILURE
    elif outcome == "incorrect" and row.get("target") == "context_policy":
        kind = FailureKind.CONTEXT_CONFLICT
    elif outcome == "fn":
        context = row.get("context_summary") or {}
        temporal = row.get("temporal_summary") or {}
        decision = row.get("decision_summary") or {}
        if (
            isinstance(context, dict)
            and context.get("policy_action") == "full_bypass"
        ):
            kind = FailureKind.CONTEXT_CONFLICT
        elif (
            isinstance(temporal, dict)
            and temporal.get("confirmed") is False
            and isinstance(decision, dict)
            and decision.get("classification") == "violation"
        ):
            kind = FailureKind.TEMPORAL_MISS
        else:
            kind = FailureKind.FALSE_NEGATIVE
    elif outcome == "fp":
        kind = FailureKind.FALSE_POSITIVE
    else:
        return None
    return FailureCase(
        sample_id=str(row.get("sample_id") or ""),
        config_id=str(row.get("config_id") or ""),
        kind=kind,
    )
