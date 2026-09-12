"""Fuse NudeNet candidates with optional local context evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from app import config
from app.vision.capture import CapturedFrame
from app.vision.regions import (
    Region,
    crop_region,
    make_context_crop,
    map_box_to_original,
    tile_regions,
)


class ContextSensor(Protocol):
    """Context classifier interface used by the decision engine."""

    def classify(self, bgr_image: np.ndarray) -> dict[str, float] | None:
        ...


class LocalNudityDetector(Protocol):
    """NudeNet interface reused for local rescue rechecks."""

    def check(self, image: np.ndarray) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class _RescueSchedule:
    next_tile_index: int = 0
    pinned_tile_index: int | None = None
    pinned_checks_remaining: int = 0


class DecisionEngine:
    """Apply conservative context confirmation to NudeNet results."""

    def __init__(
        self,
        context_classifier: ContextSensor | None = None,
        local_detector: LocalNudityDetector | None = None,
        *,
        borderline_margin: float = config.NUDENET_BORDERLINE_MARGIN,
        crop_expansion: float = config.CONTEXT_CROP_EXPANSION,
        porn_confirm_threshold: float = config.CONTEXT_PORN_CONFIRM_THRESHOLD,
        rescue_enabled: bool = config.RESCUE_ENABLED,
        rescue_porn_threshold: float = config.CONTEXT_PORN_RESCUE_THRESHOLD,
        rescue_rows: int = config.RESCUE_TILE_ROWS,
        rescue_columns: int = config.RESCUE_TILE_COLUMNS,
        pin_followup_checks: int = config.CONFIRMATION_WINDOW_SIZE - 1,
    ) -> None:
        self.context_classifier = context_classifier
        self.local_detector = local_detector
        self.borderline_margin = borderline_margin
        self.crop_expansion = crop_expansion
        self.porn_confirm_threshold = porn_confirm_threshold
        self.rescue_enabled = rescue_enabled
        self.rescue_porn_threshold = rescue_porn_threshold
        self.rescue_rows = rescue_rows
        self.rescue_columns = rescue_columns
        self.pin_followup_checks = max(0, pin_followup_checks)
        self._rescue_schedules: dict[int, _RescueSchedule] = {}

    def evaluate(
        self,
        nudenet_result: dict[str, Any],
        captured_frame: CapturedFrame,
        *,
        monitor_index: int = 1,
    ) -> dict[str, Any]:
        """Return a candidate decision without retaining image pixels."""

        result = dict(nudenet_result)
        if bool(result.get("blocked")):
            return self._strong_nudenet_result(result, captured_frame)

        borderline = self._strongest_borderline(result.get("check_points", []))
        if borderline is None:
            base = self._with_metadata(result, source="nudenet_none")
        else:
            base = self._evaluate_borderline(result, captured_frame, borderline)
            if bool(base.get("blocked")):
                return base

        return self._evaluate_rescue(base, captured_frame, monitor_index)

    def _evaluate_borderline(
        self,
        result: dict[str, Any],
        captured_frame: CapturedFrame,
        borderline: dict[str, Any],
    ) -> dict[str, Any]:
        """Allow only local Porn context to confirm borderline NudeNet."""

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

    def _evaluate_rescue(
        self,
        base: dict[str, Any],
        captured_frame: CapturedFrame,
        monitor_index: int,
    ) -> dict[str, Any]:
        """Use one rotating context tile to propose a local NudeNet recheck."""

        if (
            not self.rescue_enabled
            or self.context_classifier is None
            or self.local_detector is None
        ):
            return base
        regions = tile_regions(
            captured_frame.original_frame.shape,
            self.rescue_rows,
            self.rescue_columns,
        )
        if not regions:
            return base

        tile_index, was_pinned = self._select_rescue_tile(
            monitor_index,
            len(regions),
        )
        region = regions[tile_index]
        tile = crop_region(captured_frame.original_frame, region)
        if tile is None:
            return base

        base["rescue_tile_index"] = tile_index
        base["rescue_region"] = region
        context_scores = self.context_classifier.classify(tile)
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
        if porn_score < self.rescue_porn_threshold:
            return base

        local_result = dict(self.local_detector.check(tile))
        base["local_check_points"] = local_result.get("check_points", [])
        base["local_box"] = local_result.get("box")
        if not bool(local_result.get("blocked")):
            return base

        if not was_pinned and self.pin_followup_checks:
            schedule = self._rescue_schedules[monitor_index]
            schedule.pinned_tile_index = tile_index
            schedule.pinned_checks_remaining = self.pin_followup_checks

        label = local_result.get("label")
        confidence = float(local_result.get("confidence", 0.0))
        threshold = config.BLOCK_THRESHOLDS.get(str(label))
        base.update(
            {
                "blocked": True,
                "reason": (
                    f"local rescue found {label} score {confidence:.2f} "
                    f"after context porn score {porn_score:.2f}"
                ),
                "label": label,
                "confidence": confidence,
                "source": "rescue_tile",
                "region": region,
                "nudenet_label": label,
                "nudenet_score": confidence,
                "threshold": threshold,
            }
        )
        return base

    def _select_rescue_tile(
        self,
        monitor_index: int,
        tile_count: int,
    ) -> tuple[int, bool]:
        schedule = self._rescue_schedules.setdefault(
            monitor_index,
            _RescueSchedule(),
        )
        if schedule.pinned_tile_index is not None:
            tile_index = schedule.pinned_tile_index % tile_count
            schedule.pinned_checks_remaining -= 1
            if schedule.pinned_checks_remaining <= 0:
                schedule.pinned_tile_index = None
                schedule.pinned_checks_remaining = 0
            return tile_index, True

        tile_index = schedule.next_tile_index % tile_count
        schedule.next_tile_index = (tile_index + 1) % tile_count
        return tile_index, False

    def reset(self) -> None:
        """Clear pinned and rotating rescue state after an intervention."""

        self._rescue_schedules.clear()

    def rescue_status(self, monitor_index: int) -> dict[str, int | None]:
        """Return scalar scheduling state without exposing any image data."""

        schedule = self._rescue_schedules.get(monitor_index, _RescueSchedule())
        return {
            "next_tile_index": schedule.next_tile_index,
            "pinned_tile_index": schedule.pinned_tile_index,
            "pinned_checks_remaining": schedule.pinned_checks_remaining,
        }

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
                "rescue_tile_index": None,
                "rescue_region": None,
                "local_check_points": None,
                "local_box": None,
            }
        )
        return result
