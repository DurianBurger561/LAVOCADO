"""Load NudeNet and emit typed primary detection evidence."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from nudenet import NudeDetector

from app import config
from app.vision.detectors.base import DetectionEvidence, to_detection_evidence
from app.vision.model_assets import resolve_nudenet_model_path

LOGGER = logging.getLogger(__name__)


class DetectionModel(Protocol):
    """Raw NudeNet inference boundary."""

    def detect(self, image: np.ndarray) -> list[dict[str, Any]]: ...


class NudeNetPrimaryDetector:
    """Initialize NudeNet 640m with 320n fallback and standardize outputs."""

    def __init__(
        self,
        model: DetectionModel | None = None,
        *,
        model_factory: Callable[..., DetectionModel] = NudeDetector,
        model_path: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        self.model_variant = "injected"
        self.inference_resolution: int | None = None
        if model is not None:
            self.model = model
            return

        resolved_path = (
            Path(model_path)
            if model_path is not None and Path(model_path).is_file()
            else resolve_nudenet_model_path(
                data_dir=None if data_dir is None else Path(data_dir)
            )
        )
        if resolved_path is not None:
            try:
                self.model = model_factory(
                    model_path=str(resolved_path),
                    inference_resolution=config.NUDENET_INFERENCE_RESOLUTION,
                )
                self.model_variant = "640m"
                self.inference_resolution = config.NUDENET_INFERENCE_RESOLUTION
                return
            except Exception:
                LOGGER.exception(
                    "Could not load NudeNet 640m from %s; using bundled 320n",
                    resolved_path,
                )

        LOGGER.warning(
            "NudeNet 640m is unavailable; using bundled 320n at %s pixels",
            config.NUDENET_FALLBACK_INFERENCE_RESOLUTION,
        )
        self.model = model_factory(
            inference_resolution=config.NUDENET_FALLBACK_INFERENCE_RESOLUTION,
        )
        self.model_variant = "320n-fallback"
        self.inference_resolution = config.NUDENET_FALLBACK_INFERENCE_RESOLUTION

    @property
    def name(self) -> str:
        if self.model_variant == "320n-fallback":
            return "nudenet_320n"
        return "nudenet_640m"

    def detect(
        self,
        frame: np.ndarray,
        *,
        input_size: int,
    ) -> list[DetectionEvidence]:
        """Run NudeNet. ``input_size`` is recorded; NudeNet resizes internally."""

        del input_size
        if not isinstance(frame, np.ndarray):
            return []
        detections = list(self.model.detect(frame))
        return to_detection_evidence(detections, model=self.name)
