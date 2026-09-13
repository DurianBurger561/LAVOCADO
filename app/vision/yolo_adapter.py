"""Optional YOLO11 adapter. Maps anatomy and sexual-act labels to evidence."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app import config
from app.vision.model_assets import resolve_yolo_model_path
from app.vision.violation_policy import (
    ViolationEvidence,
    evidence_type_for_label,
)

LOGGER = logging.getLogger(__name__)


class YoloDetectionModel(Protocol):
    """Minimal detect() interface used by the adapter and tests."""

    def detect(self, image: np.ndarray) -> list[dict[str, Any]]:
        ...


def yolo_is_requested(
    *,
    enabled: bool | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return whether YOLO11 NSFW Small should load as the primary detector."""

    if enabled is None:
        enabled = config.YOLO_ENABLED
    if enabled:
        return True
    environ = os.environ if environ is None else environ
    return bool(str(environ.get("LAVOCADO_YOLO_MODEL", "")).strip())


def xyxy_to_xywh(
    box: Sequence[float],
) -> tuple[float, float, float, float] | None:
    """Convert ultralytics XYXY into the NudeNet-style XYWH box used by ROI."""

    if len(box) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    width = x2 - x1
    height = y2 - y1
    if width <= 0 or height <= 0:
        return None
    return (x1, y1, width, height)


def _bbox_from_detection(detection: dict[str, Any]) -> tuple[float, float, float, float] | None:
    box = detection.get("box")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        values = tuple(float(value) for value in box)
    except (TypeError, ValueError):
        return None
    if str(detection.get("box_format", "xywh")).strip().lower() == "xyxy":
        return xyxy_to_xywh(values)
    return values


def detections_to_evidence(
    detections: list[dict[str, Any]],
    *,
    model: str = "yolo11",
    frame_sequence: int = 0,
) -> list[ViolationEvidence]:
    """Convert YOLO-style {class, score, box} rows into violation evidence."""

    evidence: list[ViolationEvidence] = []
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        label = str(detection.get("class", "")).strip()
        evidence_type = evidence_type_for_label(label)
        if evidence_type is None:
            continue
        try:
            confidence = float(detection.get("score", 0.0))
        except (TypeError, ValueError):
            continue
        evidence.append(
            ViolationEvidence(
                evidence_type=evidence_type,
                label=label,
                confidence=max(0.0, min(1.0, confidence)),
                bbox=_bbox_from_detection(detection),
                model=model,
                frame_sequence=frame_sequence,
            )
        )
    return evidence


class UltralyticsYoloModel:
    """Adapt an ultralytics YOLO object to the detect() protocol."""

    def __init__(self, model: Any, *, imgsz: int | None = None) -> None:
        self._model = model
        self.imgsz = imgsz

    def detect(self, image: np.ndarray) -> list[dict[str, Any]]:
        rgb = np.ascontiguousarray(image[:, :, ::-1])
        kwargs: dict[str, Any] = {"verbose": False}
        if self.imgsz is not None:
            kwargs["imgsz"] = int(self.imgsz)
        try:
            results = self._model.predict(rgb, **kwargs)
        except TypeError:
            results = self._model.predict(rgb, verbose=False)
        detections: list[dict[str, Any]] = []
        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            xyxy_rows = getattr(boxes, "xyxy", None)
            confs = getattr(boxes, "conf", None)
            classes = getattr(boxes, "cls", None)
            if xyxy_rows is None or confs is None or classes is None:
                continue
            for index, raw_box in enumerate(xyxy_rows):
                xywh = xyxy_to_xywh(_row_values(raw_box))
                if xywh is None:
                    continue
                class_id = int(_scalar(classes[index]))
                detections.append(
                    {
                        "class": str(names.get(class_id, class_id)),
                        "score": float(_scalar(confs[index])),
                        "box": list(xywh),
                        "box_format": "xywh",
                    }
                )
        return detections


def _row_values(value: object) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        return []
    return [float(item) for item in value]


def _scalar(value: object) -> float:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        value = value[0]
    return float(value)


class Yolo11Adapter:
    """Run an injected YOLO detector and emit unified ViolationEvidence."""

    def __init__(
        self,
        model: YoloDetectionModel,
        *,
        model_name: str = "yolo11",
    ) -> None:
        self.model = model
        self.model_name = model_name

    def detect_evidence(
        self,
        image: np.ndarray,
        *,
        frame_sequence: int = 0,
    ) -> list[ViolationEvidence]:
        if not isinstance(image, np.ndarray):
            return []
        try:
            detections = list(self.model.detect(image))
        except Exception:
            LOGGER.exception("YOLO11 inference failed; ignoring YOLO evidence")
            return []
        return detections_to_evidence(
            detections,
            model=self.model_name,
            frame_sequence=frame_sequence,
        )


def _load_ultralytics_model(model_path: str) -> YoloDetectionModel:
    from ultralytics import YOLO

    return UltralyticsYoloModel(YOLO(model_path))


def load_yolo_adapter(
    *,
    enabled: bool | None = None,
    model_factory: Callable[[], YoloDetectionModel] | None = None,
    environ: Mapping[str, str] | None = None,
    data_dir: str | Path | None = None,
) -> Yolo11Adapter | None:
    """Load the pinned YOLO11 NSFW Small model. Missing deps never crash protection."""

    environ = os.environ if environ is None else environ
    if not yolo_is_requested(enabled=enabled, environ=environ):
        LOGGER.info("YOLO11 adapter is disabled")
        return None
    factory = model_factory
    if factory is None:
        model_path = resolve_yolo_model_path(
            environ=environ,
            data_dir=None if data_dir is None else Path(data_dir),
        )
        if model_path is None:
            LOGGER.info("YOLO11 weights are unavailable; continuing NudeNet-only")
            return None
        path = str(model_path)
        factory = lambda path=path: _load_ultralytics_model(path)
    try:
        return Yolo11Adapter(factory())
    except ImportError:
        LOGGER.warning(
            "YOLO11 dependencies are unavailable; continuing NudeNet-only"
        )
        return None
    except Exception:
        LOGGER.exception("YOLO11 adapter is unavailable; continuing without it")
        return None
