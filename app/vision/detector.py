"""Convert NudeNet detections into a LAVOCADO blocking decision."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from nudenet import NudeDetector

from app import config


class DetectionModel(Protocol):
    """Small interface used by Detector and its tests."""

    def detect(self, image: np.ndarray) -> list[dict[str, Any]]:
        ...


class Detector:
    """Run NudeNet and apply LAVOCADO's configurable thresholds."""

    def __init__(self, model: DetectionModel | None = None) -> None:
        self.model = model if model is not None else NudeDetector()

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
