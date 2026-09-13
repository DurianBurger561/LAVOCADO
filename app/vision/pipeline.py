"""Vision pipeline: primary detectors plus the visual decision engine."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.platforms.capture.models import CaptureFrame
from app.vision.decision import DecisionEngine
from app.vision.detector import Detector
from app.vision.preprocessor import FramePreprocessor
from app.vision.primary_detector_set import PrimaryDetectorSet
from app.vision.scheduler import ScanPlan
from app.vision.violation_policy import VisualViolationDecision
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
        self.decision_engine = decision_engine
        self.shadow_adapter = shadow_adapter
        self.primary_detectors = PrimaryDetectorSet(
            detector,
            supplementary=yolo_adapter,
            full_input_size=full_input_size,
        )
        self.evaluate_calls = 0
        self.last_shadow: dict[str, Any] | None = None

    def evaluate(
        self,
        captured_frame: CaptureFrame,
        *,
        monitor_index: int = 1,
        scan_plan: ScanPlan | None = None,
        is_active_monitor: bool = True,
        prepared_frame: FramePreprocessor | None = None,
    ) -> VisualViolationDecision:
        """Return a visual-violation decision without retaining pixels."""

        self.evaluate_calls += 1
        prepared = prepared_frame or FramePreprocessor(captured_frame)
        prepared.require_frame(captured_frame)
        focused = scan_plan is not None and scan_plan.mode == "focused"
        if focused:
            empty = {
                "reason": "",
                "label": None,
                "confidence": 0.0,
                "box": None,
                "check_points": [],
                "evidence": [],
            }
            decided = self.decision_engine.evaluate(
                empty,
                captured_frame,
                monitor_index=monitor_index,
                extra_evidence=[],
                scan_plan=scan_plan,
                is_active_monitor=is_active_monitor,
                prepared_frame=prepared,
            )
        else:
            from app.vision.detectors.base import check_result_from_evidence

            detected = self.primary_detectors.detect(prepared)
            nudenet_result = check_result_from_evidence(list(detected.primary))
            decided = self.decision_engine.evaluate(
                nudenet_result,
                captured_frame,
                monitor_index=monitor_index,
                extra_evidence=list(detected.supplementary),
                scan_plan=scan_plan,
                is_active_monitor=is_active_monitor,
                prepared_frame=prepared,
            )
            decided = self._with_shadow(captured_frame, decided)
        return decided

    def _with_shadow(
        self,
        captured_frame: CaptureFrame,
        decided: VisualViolationDecision,
    ) -> VisualViolationDecision:
        if self.shadow_adapter is None:
            self.last_shadow = None
            return decided
        image = captured_frame.image
        import time as _time

        started = _time.perf_counter()
        evidence = self.shadow_adapter.detect_evidence(
            image,
            frame_sequence=int(getattr(captured_frame, "sequence", 0) or 0),
        )
        elapsed_ms = (_time.perf_counter() - started) * 1000
        strongest = max(evidence, key=lambda item: item.confidence, default=None)
        from app.vision.violation_policy import VisualViolationClassification

        primary_hit = decided.classification is VisualViolationClassification.VIOLATION
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
        return replace(decided, shadow=dict(self.last_shadow))

    def reset(self) -> None:
        """Clear tile ranking and ROI follow-up state."""

        self.decision_engine.reset()
