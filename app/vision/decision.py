"""Fuse NudeNet candidates with optional local context evidence."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from app import config
from app.vision.capture import CapturedFrame
from app.vision.regions import Region, make_context_crop, map_box_to_original


class ContextSensor(Protocol):
    """Context classifier interface used by the decision engine."""

    def classify(self, bgr_image: np.ndarray) -> dict[str, float] | None:
        ...


class DecisionEngine:
    """Apply conservative context confirmation to NudeNet results."""

    def __init__(
        self,
        context_classifier: ContextSensor | None = None,
        *,
        borderline_margin: float = config.NUDENET_BORDERLINE_MARGIN,
        crop_expansion: float = config.CONTEXT_CROP_EXPANSION,
        porn_confirm_threshold: float = config.CONTEXT_PORN_CONFIRM_THRESHOLD,
    ) -> None:
        self.context_classifier = context_classifier
        self.borderline_margin = borderline_margin
        self.crop_expansion = crop_expansion
        self.porn_confirm_threshold = porn_confirm_threshold

    def evaluate(
        self,
        nudenet_result: dict[str, Any],
        captured_frame: CapturedFrame,
    ) -> dict[str, Any]:
        """Return a candidate decision without retaining image pixels."""

        result = dict(nudenet_result)
        if bool(result.get("blocked")):
            return self._strong_nudenet_result(result, captured_frame)

        borderline = self._strongest_borderline(result.get("check_points", []))
        if borderline is None:
            return self._with_metadata(result, source="nudenet_none")

        label = str(borderline["class"])
        score = float(borderline["score"])
        threshold = float(borderline["threshold"])
        box = borderline.get("box")
        base = self._with_metadata(
            result,
            source="nudenet_borderline",
            nudenet_label=label,
            nudenet_score=score,
            threshold=threshold,
        )
        if self.context_classifier is None or not isinstance(box, (list, tuple)):
            return base

        crop_result = make_context_crop(
            captured_frame.original_frame,
            box,
            captured_frame.model_frame.shape,
            self.crop_expansion,
        )
        if crop_result is None:
            return base
        crop, region = crop_result
        base["region"] = region

        context_scores = self.context_classifier.classify(crop)
        if context_scores is None:
            return base
        context_label, context_score = max(
            context_scores.items(),
            key=lambda item: item[1],
        )
        base["context_label"] = context_label
        base["context_score"] = float(context_score)
        base["context_scores"] = dict(context_scores)

        porn_score = float(context_scores.get("porn", 0.0))
        if porn_score < self.porn_confirm_threshold:
            return base

        base.update(
            {
                "blocked": True,
                "reason": (
                    f"{label} borderline score {score:.2f} confirmed by "
                    f"local context porn score {porn_score:.2f}"
                ),
                "label": label,
                "confidence": score,
                "source": "nudenet_borderline_context",
            }
        )
        return base

    def _strong_nudenet_result(
        self,
        result: dict[str, Any],
        captured_frame: CapturedFrame,
    ) -> dict[str, Any]:
        box = result.get("box")
        region: Region | None = None
        if isinstance(box, (list, tuple)):
            region = map_box_to_original(
                box,
                captured_frame.model_frame.shape,
                captured_frame.original_frame.shape,
            )
        label = result.get("label")
        threshold = config.BLOCK_THRESHOLDS.get(str(label))
        return self._with_metadata(
            result,
            source="nudenet_full",
            region=region,
            nudenet_label=None if label is None else str(label),
            nudenet_score=float(result.get("confidence", 0.0)),
            threshold=threshold,
        )

    def _strongest_borderline(
        self,
        detections: object,
    ) -> dict[str, Any] | None:
        if not isinstance(detections, list):
            return None
        candidates: list[dict[str, Any]] = []
        for detection in detections:
            if not isinstance(detection, dict):
                continue
            label = str(detection.get("class", ""))
            threshold = config.BLOCK_THRESHOLDS.get(label)
            score = float(detection.get("score", 0.0))
            if (
                threshold is not None
                and threshold - self.borderline_margin <= score < threshold
            ):
                candidate = dict(detection)
                candidate["threshold"] = threshold
                candidates.append(candidate)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                float(item["score"]) - float(item["threshold"]),
                float(item["score"]),
            ),
        )

    @staticmethod
    def _with_metadata(
        result: dict[str, Any],
        *,
        source: str,
        region: Region | None = None,
        nudenet_label: str | None = None,
        nudenet_score: float = 0.0,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        result.update(
            {
                "source": source,
                "region": region,
                "nudenet_label": nudenet_label,
                "nudenet_score": nudenet_score,
                "threshold": threshold,
                "context_label": None,
                "context_score": None,
                "context_scores": None,
            }
        )
        return result
