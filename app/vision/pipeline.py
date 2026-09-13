"""Vision pipeline: primary detectors plus the visual decision engine."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.vision.capture import CapturedFrame
from app.vision.decision import DecisionEngine
from app.vision.detector import Detector
from app.vision.scheduler import ScanPlan
from app.vision.yolo_adapter import Yolo11Adapter


class VisionPipeline:
    """Run the selected primary detector and the decision engine for one frame.

    Callers must already have resolved Context Policy to NORMAL. This object
    never inspects application or website identity.
    """

    def __init__(
        self,
        detector: Detector,
        decision_engine: DecisionEngine,
        yolo_adapter: Yolo11Adapter | None = None,
        *,
        shadow_adapter: Yolo11Adapter | None = None,
        full_input_size: int = 640,
    ) -> None:
        self.detector = detector
        self.decision_engine = decision_engine
        self.yolo_adapter = yolo_adapter
        self.shadow_adapter = shadow_adapter
        self.full_input_size = full_input_size
        self.evaluate_calls = 0
        self.last_shadow: dict[str, Any] | None = None

    def evaluate(
        self,
        captured_frame: CapturedFrame,
        *,
        monitor_index: int = 1,
        scan_plan: ScanPlan | None = None,
        is_active_monitor: bool = True,
    ) -> dict[str, Any]:
        """Return a visual-violation decision without retaining pixels."""

        self.evaluate_calls += 1
        focused = scan_plan is not None and scan_plan.mode == "focused"
        if focused:
            empty = {
                "blocked": False,
                "reason": "",
                "label": None,
                "confidence": 0.0,
                "box": None,
                "check_points": [],
                "evidence": [],
            }
            decided = self._call_decision_engine(
                empty,
                captured_frame,
                monitor_index=monitor_index,
                extra_evidence=[],
                scan_plan=scan_plan,
                is_active_monitor=is_active_monitor,
            )
        else:
            image = captured_frame.model_frame
            if not isinstance(image, np.ndarray):
                image = captured_frame.original_frame
            detect = getattr(self.detector, "detect", None)
            if callable(detect):
                from app.vision.detectors.base import check_result_from_evidence

                evidence = detect(image, input_size=self.full_input_size)
                nudenet_result = check_result_from_evidence(evidence)
            else:
                nudenet_result = dict(self.detector.check(image))
            extra_evidence = []
            if self.yolo_adapter is not None:
                extra_image = image if isinstance(image, np.ndarray) else captured_frame.original_frame
                extra_evidence = self.yolo_adapter.detect_evidence(
                    extra_image,
                    frame_sequence=int(getattr(captured_frame, "sequence", 0) or 0),
                )
            decided = self._call_decision_engine(
                nudenet_result,
                captured_frame,
                monitor_index=monitor_index,
                extra_evidence=extra_evidence,
                scan_plan=scan_plan,
                is_active_monitor=is_active_monitor,
            )
            self._record_shadow(captured_frame, decided)
        return decided

    def _record_shadow(
        self,
        captured_frame: CapturedFrame,
        decided: dict[str, Any],
    ) -> None:
        if self.shadow_adapter is None:
            self.last_shadow = None
            return
        image = captured_frame.model_frame
        if not isinstance(image, np.ndarray):
            image = captured_frame.original_frame
        import time as _time

        started = _time.perf_counter()
        evidence = self.shadow_adapter.detect_evidence(
            image,
            frame_sequence=int(getattr(captured_frame, "sequence", 0) or 0),
        )
        elapsed_ms = (_time.perf_counter() - started) * 1000
        strongest = max(evidence, key=lambda item: item.confidence, default=None)
        primary_hit = bool(decided.get("blocked"))
        shadow_hit = strongest is not None and strongest.confidence >= 0.45
        self.last_shadow = {
            "hit": shadow_hit,
            "label": None if strongest is None else strongest.label,
            "confidence": 0.0 if strongest is None else strongest.confidence,
            "latency_ms": round(elapsed_ms, 1),
            "primary_hit": primary_hit,
            "agreement": "both_hit"
            if primary_hit and shadow_hit
            else "both_miss"
            if not primary_hit and not shadow_hit
            else "primary_only"
            if primary_hit
            else "shadow_only",
        }
        decided["shadow"] = dict(self.last_shadow)

    def _call_decision_engine(
        self,
        result: dict[str, Any],
        captured_frame: CapturedFrame,
        *,
        monitor_index: int,
        extra_evidence: list[Any],
        scan_plan: ScanPlan | None,
        is_active_monitor: bool,
    ) -> dict[str, Any]:
        try:
            return self.decision_engine.evaluate(
                result,
                captured_frame,
                monitor_index=monitor_index,
                extra_evidence=extra_evidence,
                scan_plan=scan_plan,
                is_active_monitor=is_active_monitor,
            )
        except TypeError:
            return self.decision_engine.evaluate(
                result,
                captured_frame,
                monitor_index=monitor_index,
                extra_evidence=extra_evidence,
            )

    def reset(self) -> None:
        """Clear tile ranking and ROI follow-up state."""

        reset = getattr(self.decision_engine, "reset", None)
        if callable(reset):
            reset()
