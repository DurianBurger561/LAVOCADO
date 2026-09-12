"""Convert NudeNet detections into a LAVOCADO blocking decision."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from nudenet import NudeDetector

from app import config
from app.vision.model_assets import resolve_nudenet_model_path

LOGGER = logging.getLogger(__name__)


class DetectionModel(Protocol):
    """Small interface used by Detector and its tests."""

    def detect(self, image: np.ndarray) -> list[dict[str, Any]]:
        ...


class Detector:
    """Run NudeNet and apply LAVOCADO's configurable thresholds."""

    def __init__(
        self,
        model: DetectionModel | None = None,
        *,
        model_factory: Callable[..., DetectionModel] = NudeDetector,
        model_path: str | Path | None = None,
    ) -> None:
        self.model_variant = "injected"
        self.inference_resolution: int | None = None
        if model is not None:
            self.model = model
            return

        resolved_path = (
            Path(model_path)
            if model_path is not None and Path(model_path).is_file()
            else resolve_nudenet_model_path()
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

    def check(self, image: np.ndarray) -> dict[str, Any]:
        """Return a consistent decision for one image."""

        detections = list(self.model.detect(image))
        blocking_matches: list[dict[str, Any]] = []

        for detection in detections:
            label = str(detection.get("class", ""))
            score = float(detection.get("score", 0.0))
            threshold = config.BLOCK_THRESHOLDS.get(label)

            if threshold is not None and score >= threshold:
                blocking_matches.append(
                    {
                        "label": label,
                        "score": score,
                        "threshold": threshold,
                    }
                )

        if not blocking_matches:
            return {
                "blocked": False,
                "reason": "",
                "label": None,
                "confidence": 0.0,
                "check_points": detections,
            }

        strongest = max(
            blocking_matches,
            key=lambda match: float(match["score"]),
        )

        label = str(strongest["label"])
        score = float(strongest["score"])
        threshold = float(strongest["threshold"])

        return {
            "blocked": True,
            "reason": (
                f"{label} "
                f"(score {score:.2f}, threshold {threshold:.2f})"
            ),
            "label": label,
            "confidence": score,
            "check_points": detections,
        }
