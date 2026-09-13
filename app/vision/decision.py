"""Classify primary-detector evidence. Viddexa only ranks tiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from app import config
from app.vision.capture import CapturedFrame
from app.vision.nudenet_adapter import detections_to_evidence
from app.vision.regions import (
    Region,
    crop_region,
    make_context_crop,
    map_box_to_original,
    tile_regions,
)
from app.vision.violation_policy import (
    ViolationEvidence,
    VisualViolationClassification,
    evidence_to_dict,
    is_borderline_score,
    strongest_evidence,
    threshold_for_label,
)


class ContextSensor(Protocol):
    """Tile-ranking classifier interface used by the decision engine."""

    def classify(self, bgr_image: np.ndarray) -> dict[str, float] | None:
        ...


class LocalNudityDetector(Protocol):
    """Primary detector interface reused for ROI and tile rechecks."""

    def check(self, image: np.ndarray) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class _RescueSchedule:
    next_tile_index: int = 0
    pinned_tile_index: int | None = None
    pinned_checks_remaining: int = 0


class DecisionEngine:
    """Turn visual evidence into VIOLATION / UNCERTAIN / CLEAR.

    Inputs are detector evidence, the current frame, and settings. Application
    names, hostnames, and viewing-purpose flags are not accepted.
    """

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
        extra_evidence: list[ViolationEvidence] | None = None,
    ) -> dict[str, Any]:
        """Return a candidate decision without retaining image pixels."""

        result = dict(nudenet_result)
        frame_sequence = int(getattr(captured_frame, "sequence", 0) or 0)
        extra = list(extra_evidence or [])
        if extra:
            existing = result.get("evidence")
            payload = list(existing) if isinstance(existing, list) else []
            payload.extend(evidence_to_dict(item) for item in extra)
            result["evidence"] = payload
        if bool(result.get("blocked")):
            return self._strong_primary_result(result, captured_frame)

        evidence = self._collect_evidence(result, extra_evidence, frame_sequence)
        strong = [
            item
            for item in evidence
            if (threshold := threshold_for_label(item.label)) is not None
            and item.confidence >= threshold
        ]
        if strong:
            return self._violation_from_evidence(
                result, captured_frame, strongest_evidence(strong)
            )

        borderline = self._strongest_borderline_evidence(evidence)
        if borderline is None:
            borderline_detection = self._strongest_borderline(
                result.get("check_points", [])
            )
            if borderline_detection is None:
                base = self._with_metadata(
                    result,
                    source="nudenet_none",
                    classification=VisualViolationClassification.CLEAR,
                )
            else:
                base = self._evaluate_borderline(
                    result, captured_frame, borderline_detection
                )
                if bool(base.get("blocked")):
                    return base
        else:
            detection = {
                "class": borderline.label,
                "score": borderline.confidence,
                "box": None if borderline.bbox is None else list(borderline.bbox),
                "threshold": threshold_for_label(borderline.label),
            }
            base = self._evaluate_borderline(result, captured_frame, detection)
            if bool(base.get("blocked")):
                return base

        return self._evaluate_rescue(base, captured_frame, monitor_index)

    def _collect_evidence(
        self,
        result: dict[str, Any],
        extra_evidence: list[ViolationEvidence] | None,
        frame_sequence: int,
    ) -> list[ViolationEvidence]:
        checkpoints = result.get("check_points", [])
        nudenet_evidence = (
            detections_to_evidence(
                checkpoints, model="nudenet", frame_sequence=frame_sequence
            )
            if isinstance(checkpoints, list)
            else []
        )
        extra = list(extra_evidence or [])
        return nudenet_evidence + extra

    def _evaluate_borderline(
        self,
        result: dict[str, Any],
        captured_frame: CapturedFrame,
        borderline: dict[str, Any],
    ) -> dict[str, Any]:
        """Recheck a borderline box on the original-resolution crop."""

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
            classification=VisualViolationClassification.UNCERTAIN,
        )
        original = getattr(captured_frame, "original_frame", None)
        model = getattr(captured_frame, "model_frame", None)
        if (
            self.local_detector is None
            or not isinstance(box, (list, tuple))
            or not isinstance(original, np.ndarray)
            or not hasattr(model, "shape")
        ):
            return base

        crop_result = make_context_crop(
            original,
            box,
            model.shape,
            self.crop_expansion,
        )
        if crop_result is None:
            return base
        crop, region = crop_result
        base["region"] = region

        local_result = dict(self.local_detector.check(crop))
        base["local_check_points"] = local_result.get("check_points", [])
        base["local_box"] = local_result.get("box")
        if not bool(local_result.get("blocked")):
            return base

        confirmed_label = local_result.get("label")
        confidence = float(local_result.get("confidence", 0.0))
        confirmed_threshold = threshold_for_label(str(confirmed_label))
        base.update(
            {
                "blocked": True,
                "classification": VisualViolationClassification.VIOLATION.value,
                "reason": (
                    f"{confirmed_label} ROI recheck score {confidence:.2f} "
                    f"after borderline {label} score {score:.2f}"
                ),
                "label": confirmed_label,
                "confidence": confidence,
                "source": "nudenet_roi",
                "nudenet_label": None if confirmed_label is None else str(confirmed_label),
                "nudenet_score": confidence,
                "threshold": confirmed_threshold,
            }
        )
        return base

    def _evaluate_rescue(
        self,
        base: dict[str, Any],
        captured_frame: CapturedFrame,
        monitor_index: int,
    ) -> dict[str, Any]:
        """Rank tiles with Viddexa, then recheck the highest-risk tile."""

        original = getattr(captured_frame, "original_frame", None)
        if (
            not self.rescue_enabled
            or self.context_classifier is None
            or self.local_detector is None
            or not isinstance(original, np.ndarray)
        ):
            return base
        regions = tile_regions(
            original.shape,
            self.rescue_rows,
            self.rescue_columns,
        )
        if not regions:
            return base

        ranked = self._rank_tiles(original, regions)
        if not ranked:
            return base

        tile_index, was_pinned = self._select_ranked_tile(monitor_index, ranked)
        chosen = next((item for item in ranked if item[1] == tile_index), ranked[0])
        risk, tile_index, region, context_scores, tile = chosen
        context_label, context_score = max(
            context_scores.items(),
            key=lambda item: item[1],
        )
        base["rescue_tile_index"] = tile_index
        base["rescue_region"] = region
        base["context_label"] = context_label
        base["context_score"] = float(context_score)
        base["context_scores"] = dict(context_scores)

        if not was_pinned and risk < self.rescue_porn_threshold:
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
        threshold = threshold_for_label(str(label))
        base.update(
            {
                "blocked": True,
                "classification": VisualViolationClassification.VIOLATION.value,
                "reason": (
                    f"local rescue found {label} score {confidence:.2f} "
                    f"after tile rank score {risk:.2f}"
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

    def _rank_tiles(
        self,
        original: np.ndarray,
        regions: tuple[Region, ...],
    ) -> list[tuple[float, int, Region, dict[str, float], np.ndarray]]:
        ranked: list[tuple[float, int, Region, dict[str, float], np.ndarray]] = []
        assert self.context_classifier is not None
        for tile_index, region in enumerate(regions):
            tile = crop_region(original, region)
            if tile is None:
                continue
            context_scores = self.context_classifier.classify(tile)
            if context_scores is None:
                continue
            risk = max(
                float(context_scores.get("porn", 0.0)),
                float(context_scores.get("hentai", 0.0)),
            )
            ranked.append((risk, tile_index, region, dict(context_scores), tile))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return ranked

    def _select_ranked_tile(
        self,
        monitor_index: int,
        ranked: list[tuple[float, int, Region, dict[str, float], np.ndarray]],
    ) -> tuple[int, bool]:
        schedule = self._rescue_schedules.setdefault(
            monitor_index,
            _RescueSchedule(),
        )
        tile_count = len(ranked)
        if schedule.pinned_tile_index is not None:
            pinned = schedule.pinned_tile_index
            schedule.pinned_checks_remaining -= 1
            if schedule.pinned_checks_remaining <= 0:
                schedule.pinned_tile_index = None
                schedule.pinned_checks_remaining = 0
            if any(item[1] == pinned for item in ranked):
                return pinned, True

        if not ranked:
            return 0, False
        tile_index = ranked[0][1]
        schedule.next_tile_index = (tile_index + 1) % max(1, tile_count)
        return tile_index, False

    def reset(self) -> None:
        """Clear pinned and ranking state after an intervention or bypass."""

        self._rescue_schedules.clear()

    def rescue_status(self, monitor_index: int) -> dict[str, int | None]:
        """Return scalar scheduling state without exposing any image data."""

        schedule = self._rescue_schedules.get(monitor_index, _RescueSchedule())
        return {
            "next_tile_index": schedule.next_tile_index,
            "pinned_tile_index": schedule.pinned_tile_index,
            "pinned_checks_remaining": schedule.pinned_checks_remaining,
        }

    def _strong_primary_result(
        self,
        result: dict[str, Any],
        captured_frame: CapturedFrame,
    ) -> dict[str, Any]:
        box = result.get("box")
        region: Region | None = None
        model = getattr(captured_frame, "model_frame", None)
        original = getattr(captured_frame, "original_frame", None)
        if (
            isinstance(box, (list, tuple))
            and hasattr(model, "shape")
            and hasattr(original, "shape")
        ):
            region = map_box_to_original(
                box,
                model.shape,
                original.shape,
            )
        label = result.get("label")
        threshold = threshold_for_label(str(label))
        return self._with_metadata(
            result,
            source="nudenet_full",
            region=region,
            nudenet_label=None if label is None else str(label),
            nudenet_score=float(result.get("confidence", 0.0)),
            threshold=threshold,
            classification=VisualViolationClassification.VIOLATION,
        )

    def _violation_from_evidence(
        self,
        result: dict[str, Any],
        captured_frame: CapturedFrame,
        evidence: ViolationEvidence | None,
    ) -> dict[str, Any]:
        if evidence is None:
            return self._strong_primary_result(result, captured_frame)
        box = None if evidence.bbox is None else list(evidence.bbox)
        payload = dict(result)
        payload.update(
            {
                "blocked": True,
                "label": evidence.label,
                "confidence": evidence.confidence,
                "box": box,
                "reason": (
                    f"{evidence.label} "
                    f"(score {evidence.confidence:.2f}, {evidence.model})"
                ),
                "evidence": list(result.get("evidence") or [])
                or [evidence_to_dict(evidence)],
            }
        )
        decided = self._strong_primary_result(payload, captured_frame)
        decided["source"] = (
            "yolo_sexual_act"
            if evidence.evidence_type.value == "sexual_act"
            else f"{evidence.model}_full"
        )
        return decided

    def _strongest_borderline_evidence(
        self,
        evidence: list[ViolationEvidence],
    ) -> ViolationEvidence | None:
        candidates: list[ViolationEvidence] = []
        for item in evidence:
            threshold = threshold_for_label(item.label)
            if threshold is None:
                continue
            if is_borderline_score(
                item.confidence, threshold, self.borderline_margin
            ):
                candidates.append(item)
        return strongest_evidence(candidates)

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
            threshold = threshold_for_label(label)
            score = float(detection.get("score", 0.0))
            if threshold is not None and is_borderline_score(
                score, threshold, self.borderline_margin
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
        classification: VisualViolationClassification | None = None,
    ) -> dict[str, Any]:
        if classification is None:
            classification = (
                VisualViolationClassification.VIOLATION
                if bool(result.get("blocked"))
                else VisualViolationClassification.CLEAR
            )
        evidence_payload = result.get("evidence")
        if not isinstance(evidence_payload, list):
            evidence_payload = [
                evidence_to_dict(item)
                for item in detections_to_evidence(
                    result.get("check_points", [])
                    if isinstance(result.get("check_points"), list)
                    else []
                )
            ]
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
                "classification": classification.value,
                "blocked": classification is VisualViolationClassification.VIOLATION,
                "evidence": evidence_payload,
            }
        )
        return result
