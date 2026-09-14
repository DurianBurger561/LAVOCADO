"""YOLO11 NSFW Small primary detector with its own labels and input sizes."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np

from app.vision.detectors.base import (
    DetectionEvidence,
    to_detection_evidence,
)
from app.vision.yolo_adapter import (
    Yolo11Adapter,
    YoloDetectionModel,
    load_yolo_adapter,
)


class Yolo11NsfwDetector:
    """Run YOLO11 as a selectable primary detector, never as a Block oracle."""

    def __init__(
        self,
        adapter: Yolo11Adapter,
        *,
        default_input_size: int = 640,
    ) -> None:
        self._adapter = adapter
        self.default_input_size = int(default_input_size)
        self.model_variant = "yolo11-nsfw-small"
        self.inference_resolution = self.default_input_size

    @property
    def name(self) -> str:
        return "yolo11_nsfw_small"

    def detect(
        self,
        frame: np.ndarray,
        *,
        input_size: int,
    ) -> list[DetectionEvidence]:
        if not isinstance(frame, np.ndarray):
            return []
        model = self._adapter.model
        previous = getattr(model, "imgsz", None)
        if hasattr(model, "imgsz"):
            model.imgsz = int(input_size)
        try:
            detections = list(model.detect(frame))
        except Exception:  # noqa: BLE001 - inference must not crash protection
            return []
        finally:
            if hasattr(model, "imgsz"):
                model.imgsz = previous
        return to_detection_evidence(detections, model=self.name)


def load_yolo11_nsfw_detector(
    *,
    enabled: bool | None = None,
    model_factory: Callable[[], YoloDetectionModel] | None = None,
    environ: Mapping[str, str] | None = None,
    default_input_size: int = 640,
    data_dir: object | None = None,
) -> Yolo11NsfwDetector | None:
    adapter = load_yolo_adapter(
        enabled=enabled,
        model_factory=model_factory,
        environ=environ,
        data_dir=data_dir,  # type: ignore[arg-type]
    )
    if adapter is None:
        return None
    return Yolo11NsfwDetector(adapter, default_input_size=default_input_size)
