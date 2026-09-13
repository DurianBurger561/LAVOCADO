"""Classify primary-detector evidence. Viddexa only ranks tiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from app import config
from app.settings.schema import VisionSettings, default_vision_settings
from app.vision.capture import CapturedFrame
from app.vision.change_map import build_change_map, tile_change_scores
from app.vision.evidence import evidence_from_confidence
from app.vision.detectors.base import DetectionEvidence
from app.vision.nudenet_adapter import detections_to_evidence
from app.vision.regions import (
    Region,
    crop_region,
    make_context_crop,
    map_box_to_original,
    overlapping_tile_regions,
    subdivide_region,
    tile_regions,
)
from app.vision.scheduler import ScanPlan, VisionScheduler
from app.vision.tiles import TileState, mark_checked, rank_tiles
from app.vision.tracking import CandidateTracker, box_to_region
from app.vision.violation_policy import (
    DetectionTier,
    ThresholdPolicy,
    ViolationEvidence,
    ViolationEvidenceType,
    VisualViolationClassification,
    VisualViolationDecision,
    evidence_to_dict,
    is_borderline_score,
    strongest_evidence,
    threshold_for_label,
    tier_for_score,
    visual_decision_from_engine_payload,
)


class ContextSensor(Protocol):
    """Tile-ranking classifier interface used by the decision engine."""

    def classify(self, bgr_image: np.ndarray) -> dict[str, float] | None:
        ...


class LocalNudityDetector(Protocol):
    """Primary detector interface reused for ROI and tile rechecks."""

    def detect(
        self,
        frame: np.ndarray,
        *,
        input_size: int,
    ) -> list[DetectionEvidence]:
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
        settings: VisionSettings | None = None,
        tracker: CandidateTracker | None = None,
        tile_overlap: float | None = None,
        max_tile_skip: int | None = None,
        checks_per_scan: int | None = None,
    ) -> None:
        self.context_classifier = context_classifier
        self.local_detector = local_detector
        self.borderline_margin = borderline_margin
        self.crop_expansion = crop_expansion
        self.porn_confirm_threshold = porn_confirm_threshold
        self.rescue_enabled = rescue_enabled
        # Kept for diagnostics compatibility. Viddexa no longer gates tile checks.
        self.rescue_porn_threshold = rescue_porn_threshold
        self.rescue_rows = rescue_rows
        self.rescue_columns = rescue_columns
        self.pin_followup_checks = max(0, pin_followup_checks)
        self.settings = settings or default_vision_settings()
        self.tile_overlap = (
            float(config.RESCUE_TILE_OVERLAP) if tile_overlap is None else tile_overlap
        )
        self.max_tile_skip = (
            int(config.RESCUE_MAX_TILE_SKIP) if max_tile_skip is None else max_tile_skip
        )
        self.checks_per_scan = (
            int(config.RESCUE_CHECKS_PER_SCAN) if checks_per_scan is None else checks_per_scan
        )
        self.tracker = tracker or CandidateTracker()
        self.threshold_policy = ThresholdPolicy.from_settings(self.settings)
        self.scheduler = VisionScheduler(self.settings)
        self._rescue_schedules: dict[int, _RescueSchedule] = {}
        self._tiles: dict[int, list[TileState]] = {}
        self._previous_gray: dict[int, object] = {}
        self._scan_ids: dict[int, int] = {}
        self._last_plan: dict[int, ScanPlan] = {}

    def _strong_local_hit(self, crop: np.ndarray) -> DetectionEvidence | None:
        if self.local_detector is None or not isinstance(crop, np.ndarray):
            return None
        evidence = list(
            self.local_detector.detect(
                crop,
                input_size=self.settings.detector.tile_input_size,
            )
        )
        strong = [
            item
            for item in evidence
            if self.threshold_policy.tier(item.confidence, item.label, item.model)
            is DetectionTier.STRONG
        ]
        if not strong:
            return None
        return max(strong, key=lambda item: item.confidence)

    def evaluate(
        self,
        nudenet_result: dict[str, Any],
        captured_frame: CapturedFrame,
        *,
        monitor_index: int = 1,
        extra_evidence: list[ViolationEvidence] | None = None,
        scan_plan: ScanPlan | None = None,
        is_active_monitor: bool = True,
    ) -> VisualViolationDecision:
        """Return a candidate decision without retaining image pixels."""

        result = dict(nudenet_result)
        for key in ("hostname", "application_name", "url", "medical", "art", "education"):
            result.pop(key, None)
        frame_sequence = int(getattr(captured_frame, "sequence", 0) or 0)
        extra = list(extra_evidence or [])
        if extra:
            existing = result.get("evidence")
            payload = list(existing) if isinstance(existing, list) else []
            payload.extend(evidence_to_dict(item) for item in extra)
            result["evidence"] = payload

        plan = scan_plan
        if plan is None:
            active = self.tracker.active_track(monitor_index)
            if active is not None:
                original = getattr(captured_frame, "original_frame", None)
                roi = active.box
                if isinstance(original, np.ndarray):
                    predicted = self.tracker.predicted_roi(
                        active, original.shape, self.crop_expansion
                    )
                    if predicted is not None:
                        roi = predicted
                        active.box = predicted
                plan = ScanPlan(
                    mode="focused",
                    run_full=False,
                    tile_indexes=(),
                    roi=roi,
                    subdivide=False,
                    input_size=self.settings.detector.tile_input_size,
                    interval_ms=self.settings.scan.candidate_interval_ms,
                )
                self._last_plan[monitor_index] = plan
        if plan is not None and plan.mode == "focused" and plan.roi is not None:
            focused = self._evaluate_focused(
                result,
                captured_frame,
                monitor_index,
                plan.roi,
                frame_sequence,
            )
            return self._finalize_decision(
                focused, captured_frame, monitor_index, frame_sequence
            )

        if bool(result.get("blocked")):
            decided = self._confirm_primary_candidate(
                result,
                captured_frame,
                None,
                confirmed_source="nudenet_roi",
                candidate_source="anatomy_candidate",
                fallback=self._strong_primary_result(result, captured_frame),
            )
            return self._finalize_decision(
                decided, captured_frame, monitor_index, frame_sequence
            )

        evidence = self._collect_evidence(result, extra_evidence, frame_sequence)
        strong = [
            item
            for item in evidence
            if self.threshold_policy.tier(
                item.confidence, item.label, item.model
            )
            is DetectionTier.STRONG
        ]
        if strong:
            chosen = strongest_evidence(strong)
            sexual_act = (
                chosen is not None
                and chosen.evidence_type is ViolationEvidenceType.SEXUAL_ACT
            )
            decided = self._confirm_primary_candidate(
                result,
                captured_frame,
                chosen,
                confirmed_source=(
                    "yolo_sexual_act_roi" if sexual_act else "anatomy_roi"
                ),
                candidate_source=(
                    "sexual_act_candidate" if sexual_act else "anatomy_candidate"
                ),
                fallback=self._violation_from_evidence(
                    result, captured_frame, chosen
                ),
            )
            return self._finalize_decision(
                decided, captured_frame, monitor_index, frame_sequence
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
                    return self._finalize_decision(
                        base, captured_frame, monitor_index, frame_sequence
                    )
        else:
            detection = {
                "class": borderline.label,
                "score": borderline.confidence,
                "box": None if borderline.bbox is None else list(borderline.bbox),
                "threshold": self.threshold_policy.strong(
                    borderline.label, borderline.model
                ),
            }
            base = self._evaluate_borderline(result, captured_frame, detection)
            if bool(base.get("blocked")):
                return self._finalize_decision(
                    base, captured_frame, monitor_index, frame_sequence
                )

        if plan is None:
            plan = self.prepare_scan(
                captured_frame,
                monitor_index,
                is_active_monitor=is_active_monitor,
            )
        decided = self._evaluate_rescue(
            base, captured_frame, monitor_index, plan=plan
        )
        return self._finalize_decision(
            decided, captured_frame, monitor_index, frame_sequence
        )

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

    def _confirm_primary_candidate(
        self,
        result: dict[str, Any],
        captured_frame: CapturedFrame,
        evidence: ViolationEvidence | None,
        *,
        confirmed_source: str,
        candidate_source: str,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        """Confirm primary visual evidence on an original-resolution ROI.

        Temporal confirmation still happens on a later fresh frame. Viddexa is
        not consulted: this is visual evidence, not viewing purpose.
        """

        if evidence is not None:
            label = evidence.label
            score = evidence.confidence
            box: object = evidence.bbox
        else:
            label = result.get("label")
            score = float(result.get("confidence", 0.0) or 0.0)
            box = result.get("box")
        if (
            not self.settings.recheck.enabled
            or self.local_detector is None
            or not isinstance(box, (list, tuple))
        ):
            return fallback
        detection = {
            "class": str(label),
            "score": score,
            "box": list(box),
            "threshold": threshold_for_label(str(label)),
        }
        roi = self._evaluate_borderline(result, captured_frame, detection)
        if bool(roi.get("blocked")):
            roi["source"] = confirmed_source
            roi["reason"] = (
                f"{label} original-resolution ROI recheck "
                f"after score {score:.2f}"
            )
            return roi
        if roi.get("local_check_points") is None:
            return fallback
        roi["source"] = candidate_source
        roi["label"] = label
        roi["confidence"] = score
        return roi

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
            not self.settings.recheck.enabled
            or self.local_detector is None
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

        hit = self._strong_local_hit(crop)
        base["local_check_points"] = []
        base["local_box"] = None if hit is None or hit.box is None else list(hit.box)
        if hit is None:
            return base

        confirmed_label = hit.label
        confidence = float(hit.confidence)
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
        plan: ScanPlan | None = None,
    ) -> dict[str, Any]:
        """Check priority tiles. Viddexa only orders them; it never vetoes."""

        original = getattr(captured_frame, "original_frame", None)
        if (
            not self.rescue_enabled
            or self.local_detector is None
            or not isinstance(original, np.ndarray)
        ):
            return base

        tiles = self._tiles_for(monitor_index, original)
        if not tiles:
            return base

        tile_indexes = list(plan.tile_indexes) if plan is not None else []
        if not tile_indexes:
            ranked = rank_tiles(tiles, max_skip=self.max_tile_skip)
            tile_indexes = [item.index for item in ranked[: max(1, self.checks_per_scan)]]

        ranking_payload = [
            {"index": tile.index, "priority": tile.priority_score}
            for tile in rank_tiles(list(tiles), max_skip=self.max_tile_skip)
        ]
        base["tile_ranking"] = ranking_payload

        checked: set[int] = set()
        scan_id = self._scan_ids.get(monitor_index, 0)
        decided = base
        for tile_index in tile_indexes:
            tile_state = next((item for item in tiles if item.index == tile_index), None)
            if tile_state is None:
                continue
            crop = crop_region(original, tile_state.region)
            if crop is None:
                continue
            checked.add(tile_index)
            context_scores = dict(tile_state.context_scores)
            if context_scores:
                context_label, context_score = max(
                    context_scores.items(),
                    key=lambda item: item[1],
                )
            else:
                context_label, context_score = "none", 0.0
            schedule = self._rescue_schedules.setdefault(
                monitor_index, _RescueSchedule()
            )
            schedule.next_tile_index = (tile_index + 1) % max(1, len(tiles))
            decided["rescue_tile_index"] = tile_index
            decided["rescue_region"] = tile_state.region
            decided["context_label"] = context_label
            decided["context_score"] = float(context_score)
            decided["context_scores"] = context_scores or None

            hit = self._strong_local_hit(crop)
            decided["local_box"] = None if hit is None or hit.box is None else list(hit.box)
            if hit is not None:
                if self.pin_followup_checks:
                    schedule = self._rescue_schedules.setdefault(
                        monitor_index, _RescueSchedule()
                    )
                    schedule.pinned_tile_index = tile_index
                    schedule.pinned_checks_remaining = self.pin_followup_checks
                label = hit.label
                confidence = float(hit.confidence)
                threshold = threshold_for_label(str(label))
                decided.update(
                    {
                        "blocked": True,
                        "classification": VisualViolationClassification.VIOLATION.value,
                        "reason": (
                            f"local rescue found {label} score {confidence:.2f} "
                            f"after tile priority {tile_state.priority_score:.2f}"
                        ),
                        "label": label,
                        "confidence": confidence,
                        "source": "rescue_tile",
                        "region": tile_state.region,
                        "nudenet_label": label,
                        "nudenet_score": confidence,
                        "threshold": threshold,
                        "tier": DetectionTier.STRONG.value,
                    }
                )
                mark_checked(tiles, checked, scan_id)
                return decided

            if (
                plan is not None
                and plan.subdivide
                and tile_state.context_score >= 0.6
                and tile_state.change_score >= 0.4
            ):
                subdivided = self._evaluate_subtiles(
                    decided, original, tile_state, monitor_index
                )
                if bool(subdivided.get("blocked")):
                    checked.add(tile_index)
                    mark_checked(tiles, checked, scan_id)
                    return subdivided

        mark_checked(tiles, checked, scan_id)
        return decided

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
        self._tiles.clear()
        self._previous_gray.clear()
        self._scan_ids.clear()
        self._last_plan.clear()
        self.tracker.reset()
        self.scheduler.reset()

    def prepare_scan(
        self,
        captured_frame: CapturedFrame,
        monitor_index: int,
        *,
        is_active_monitor: bool = True,
    ) -> ScanPlan:
        """Refresh tile scores and ask the scheduler what to inspect next."""

        original = getattr(captured_frame, "original_frame", None)
        tiles: list[TileState] = []
        change_map = None
        if isinstance(original, np.ndarray):
            tiles = self._tiles_for(monitor_index, original)
            previous = self._previous_gray.get(monitor_index)
            change_map = build_change_map(
                original,
                previous if isinstance(previous, np.ndarray) else None,
            )
            if change_map is not None:
                self._previous_gray[monitor_index] = change_map.gray
                scores = tile_change_scores(
                    change_map,
                    tuple(tile.region for tile in tiles),
                    original.shape,
                )
                for tile, score in zip(tiles, scores, strict=False):
                    tile.change_score = score
            self._refresh_context_scores(original, tiles)
        self._scan_ids[monitor_index] = self._scan_ids.get(monitor_index, 0) + 1
        active = self.tracker.active_track(monitor_index)
        predicted = None
        usable_frame = isinstance(original, np.ndarray)
        if active is not None and usable_frame:
            predicted = self.tracker.predicted_roi(
                active, original.shape, self.crop_expansion
            )
            if predicted is not None:
                active.box = predicted
        plan = self.scheduler.plan(
            monitor_index=monitor_index,
            tiles=tiles,
            change_map=change_map,
            active_track=active if usable_frame else None,
            is_active_monitor=is_active_monitor,
        )
        self._last_plan[monitor_index] = plan
        return plan

    def _tiles_for(self, monitor_index: int, original: np.ndarray) -> list[TileState]:
        regions = overlapping_tile_regions(
            original.shape,
            self.rescue_rows,
            self.rescue_columns,
            self.tile_overlap,
        )
        if not regions:
            regions = tile_regions(
                original.shape, self.rescue_rows, self.rescue_columns
            )
        existing = self._tiles.get(monitor_index)
        if existing is not None and len(existing) == len(regions):
            for tile, region in zip(existing, regions, strict=False):
                tile.region = region
            return existing
        tiles = [
            TileState(index=index, region=region)
            for index, region in enumerate(regions)
        ]
        self._tiles[monitor_index] = tiles
        return tiles

    def _refresh_context_scores(
        self, original: np.ndarray, tiles: list[TileState]
    ) -> None:
        crops = [crop_region(original, tile.region) for tile in tiles]
        classify_batch = getattr(self.context_classifier, "classify_batch", None)
        if callable(classify_batch):
            valid = [crop for crop in crops if crop is not None]
            results = classify_batch(valid) if valid else []
            result_index = 0
            for tile, crop in zip(tiles, crops, strict=False):
                if crop is None:
                    continue
                if result_index < len(results):
                    item = results[result_index]
                    scores = getattr(item, "scores", None) or {}
                    tile.context_scores = dict(scores)
                    tile.context_score = float(
                        max(
                            float(scores.get("porn", 0.0) or 0.0),
                            float(scores.get("hentai", 0.0) or 0.0),
                        )
                    )
                    result_index += 1
            return
        if self.context_classifier is None:
            for tile in tiles:
                tile.context_score = 0.0
                tile.context_scores = {}
            return
        for tile, crop in zip(tiles, crops, strict=False):
            if crop is None:
                continue
            scores = self.context_classifier.classify(crop)
            if not scores:
                tile.context_score = 0.0
                tile.context_scores = {}
                continue
            tile.context_scores = dict(scores)
            tile.context_score = max(
                float(scores.get("porn", 0.0) or 0.0),
                float(scores.get("hentai", 0.0) or 0.0),
            )

    def _evaluate_focused(
        self,
        result: dict[str, Any],
        captured_frame: CapturedFrame,
        monitor_index: int,
        roi: Region,
        frame_sequence: int,
    ) -> dict[str, Any]:
        original = getattr(captured_frame, "original_frame", None)
        base = self._with_metadata(
            result,
            source="focused_roi",
            region=roi,
            classification=VisualViolationClassification.CLEAR,
        )
        if self.local_detector is None or not isinstance(original, np.ndarray):
            return base
        crop = crop_region(original, roi)
        if crop is None:
            return base
        hit = self._strong_local_hit(crop)
        base["local_box"] = None if hit is None or hit.box is None else list(hit.box)
        base["region"] = roi
        if hit is None:
            track = self.tracker.active_track(monitor_index)
            if track is not None:
                self.tracker.mark_miss(track, decay=self.settings.temporal.decay)
            base["source"] = "focused_miss"
            return base
        label = hit.label
        confidence = float(hit.confidence)
        threshold = threshold_for_label(str(label))
        base.update(
            {
                "blocked": True,
                "classification": VisualViolationClassification.VIOLATION.value,
                "reason": (
                    f"{label} focused ROI score {confidence:.2f} "
                    f"on fresh frame {frame_sequence}"
                ),
                "label": label,
                "confidence": confidence,
                "source": "focused_roi",
                "nudenet_label": label,
                "nudenet_score": confidence,
                "threshold": threshold,
                "tier": DetectionTier.STRONG.value,
            }
        )
        return base

    def _evaluate_subtiles(
        self,
        base: dict[str, Any],
        original: np.ndarray,
        tile_state: TileState,
        monitor_index: int,
    ) -> dict[str, Any]:
        del monitor_index
        if self.local_detector is None:
            return base
        subtiles = subdivide_region(tile_state.region)
        if not subtiles:
            return base
        scored: list[tuple[float, Region, np.ndarray]] = []
        for region in subtiles:
            crop = crop_region(original, region)
            if crop is None:
                continue
            scores = None
            if self.context_classifier is not None:
                scores = self.context_classifier.classify(crop)
            risk = 0.0
            if scores:
                risk = max(
                    float(scores.get("porn", 0.0) or 0.0),
                    float(scores.get("hentai", 0.0) or 0.0),
                )
            scored.append((risk, region, crop))
        if not scored:
            return base
        scored.sort(key=lambda item: -item[0])
        _risk, region, crop = scored[0]
        hit = self._strong_local_hit(crop)
        base["local_box"] = None if hit is None or hit.box is None else list(hit.box)
        if hit is None:
            return base
        label = hit.label
        confidence = float(hit.confidence)
        base.update(
            {
                "blocked": True,
                "classification": VisualViolationClassification.VIOLATION.value,
                "reason": (
                    f"coarse-to-fine found {label} score {confidence:.2f}"
                ),
                "label": label,
                "confidence": confidence,
                "source": "subtile",
                "region": region,
                "nudenet_label": label,
                "nudenet_score": confidence,
                "threshold": threshold_for_label(str(label)),
                "tier": DetectionTier.STRONG.value,
            }
        )
        return base

    def _finalize_decision(
        self,
        decided: dict[str, Any],
        captured_frame: CapturedFrame,
        monitor_index: int,
        frame_sequence: int,
    ) -> VisualViolationDecision:
        plan = self._last_plan.get(monitor_index)
        if plan is not None:
            decided["scan_mode"] = plan.mode
            decided["scan_interval_ms"] = plan.interval_ms
        label = decided.get("label") or decided.get("nudenet_label")
        score = float(decided.get("confidence") or decided.get("nudenet_score") or 0.0)
        if label and "tier" not in decided:
            model = None
            payload = decided.get("evidence")
            if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                model = payload[0].get("model")
            decided["tier"] = self.threshold_policy.tier(
                score, str(label), None if model is None else str(model)
            ).value
            if decided["tier"] == DetectionTier.IGNORE.value:
                decided["tier"] = tier_for_score(
                    score, str(label), margin=self.borderline_margin
                ).value
        hit_ids: set[int] = set()
        if bool(decided.get("blocked")):
            region = decided.get("region")
            if isinstance(region, (list, tuple)) and len(region) == 4:
                mapped = box_to_region(region, xywh=False)
                region = mapped or tuple(int(v) for v in region)
            else:
                region = box_to_region(decided.get("box"), xywh=True)
            track = self.tracker.match_or_create(
                monitor_index=monitor_index,
                box=region if isinstance(region, tuple) else None,
                label=None if label is None else str(label),
                confidence=score,
                source=str(decided.get("source") or "unknown"),
                frame_sequence=frame_sequence,
                evidence_delta=evidence_from_confidence(
                    score, None if label is None else str(label)
                ),
            )
            if track is not None:
                hit_ids.add(track.id)
                decided["track_id"] = track.id
                decided["track_fresh_hits"] = track.fresh_frame_hits
                decided["track_evidence"] = track.evidence_score
                decided["region"] = track.box
        self.tracker.mark_monitor_misses(
            monitor_index,
            hit_ids=hit_ids,
            decay=self.settings.temporal.decay,
            frame_sequence=frame_sequence,
        )
        del captured_frame
        return visual_decision_from_engine_payload(
            decided,
            frame_sequence=frame_sequence,
            monitor_index=monitor_index,
        )

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
            if (
                self.threshold_policy.tier(
                    item.confidence, item.label, item.model
                )
                is DetectionTier.PROPOSAL
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
            score = float(detection.get("score", 0.0))
            model = detection.get("model")
            threshold = self.threshold_policy.strong(
                label, None if model is None else str(model)
            ) or threshold_for_label(label)
            if threshold is not None and (
                self.threshold_policy.tier(
                    score, label, None if model is None else str(model)
                )
                is DetectionTier.PROPOSAL
                or is_borderline_score(score, threshold, self.borderline_margin)
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


VisualDecisionEngine = DecisionEngine
