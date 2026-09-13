"""Vision pipeline: primary detectors plus the visual decision engine."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.vision.capture import CapturedFrame
from app.vision.decision import DecisionEngine
from app.vision.detector import Detector
from app.vision.yolo_adapter import Yolo11Adapter


class VisionPipeline:
    """Run NudeNet, optional YOLO, and the decision engine for one frame.

    Callers must already have resolved Context Policy to NORMAL. This object
    never inspects application or website identity.
    """

    def __init__(
        self,
        detector: Detector,
        decision_engine: DecisionEngine,
        yolo_adapter: Yolo11Adapter | None = None,
    ) -> None:
        self.detector = detector
        self.decision_engine = decision_engine
        self.yolo_adapter = yolo_adapter
        self.evaluate_calls = 0

    def evaluate(
        self,
        captured_frame: CapturedFrame,
        *,
        monitor_index: int = 1,
    ) -> dict[str, Any]:
        """Return a visual-violation decision without retaining pixels."""

        self.evaluate_calls += 1
        nudenet_result = dict(self.detector.check(captured_frame.model_frame))
        extra_evidence = []
        if self.yolo_adapter is not None:
            image = captured_frame.model_frame
            if not isinstance(image, np.ndarray):
                image = captured_frame.original_frame
            extra_evidence = self.yolo_adapter.detect_evidence(
                image,
                frame_sequence=int(getattr(captured_frame, "sequence", 0) or 0),
            )
        return self.decision_engine.evaluate(
            nudenet_result,
            captured_frame,
            monitor_index=monitor_index,
            extra_evidence=extra_evidence,
        )

    def reset(self) -> None:
        """Clear tile ranking and ROI follow-up state."""

        reset = getattr(self.decision_engine, "reset", None)
        if callable(reset):
            reset()
