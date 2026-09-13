"""Protection-runtime helpers that keep Context Policy in front of Vision."""

from __future__ import annotations

from typing import Any

from app.context.models import ContextPolicyAction
from app.vision.pipeline import VisionPipeline
from app.vision.violation_policy import VisualViolationClassification


def allows_vision(action: ContextPolicyAction | None) -> bool:
    """Vision runs only for NORMAL. Missing context still runs Vision."""

    return action is None or action is ContextPolicyAction.NORMAL


class VisionSession:
    """Skip detectors during FULL_BYPASS and restart cleanly when leaving it."""

    def __init__(self, pipeline: VisionPipeline) -> None:
        self.pipeline = pipeline
        self._bypass = False

    @property
    def in_bypass(self) -> bool:
        return self._bypass

    def enter_bypass(self) -> None:
        if not self._bypass:
            self.pipeline.reset()
        self._bypass = True

    def exit_bypass_if_needed(self) -> None:
        if not self._bypass:
            return
        self.pipeline.reset()
        self._bypass = False

    def evaluate(
        self,
        captured_frame: object,
        *,
        monitor_index: int = 1,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._bypass:
            return {
                "blocked": False,
                "classification": VisualViolationClassification.CLEAR.value,
                "source": "full_bypass",
                "label": None,
                "confidence": 0.0,
                "monitor_index": monitor_index,
            }
        return self.pipeline.evaluate(
            captured_frame,
            monitor_index=monitor_index,
            **kwargs,
        )
