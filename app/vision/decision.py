"""Classify primary-detector evidence. Viddexa only ranks tiles."""

from __future__ import annotations

from typing import Any

import numpy as np

from app import config
from app.platforms.capture.models import CaptureFrame
from app.settings.schema import VisionSettings, default_vision_settings
from app.vision.candidate_verifier import CandidateVerifier, LocalNudityDetector
from app.vision.evidence import evidence_from_confidence
from app.vision.preprocessor import FramePreprocessor
from app.vision.primary_detector_set import PrimaryDetection
from app.vision.regions import Region, map_box_to_original
from app.vision.scan_planner import ScanPlanner
from app.vision.scheduler import ScanPlan, TileScheduler
from app.vision.tiles import TileState
from app.vision.tracking import CandidateTracker, box_to_region
from app.vision.viddexa_ranker import ContextSensor, ViddexaRanker
from app.vision.violation_policy import (
    DetectionTier,
    ThresholdPolicy,
    ViolationEvidence,
    ViolationEvidenceType,
    VisualViolationClassification,
    VisualViolationDecision,
    evidence_to_dict,
    threshold_for_label,
    tier_for_score,
)
from app.vision.visual_decision import BorderlineCandidate, PrimaryAssessment
from app.vision.visual_decision import VisualDecisionEngine as _VisualDecisionEngine


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
        rescue_enabled: bool = config.RESCUE_ENABLED,
        rescue_rows: int = config.RESCUE_TILE_ROWS,
        rescue_columns: int = config.RESCUE_TILE_COLUMNS,
        pin_followup_checks: int = config.CONFIRMATION_WINDOW_SIZE - 1,
        settings: VisionSettings | None = None,
        tracker: CandidateTracker | None = None,
        tile_overlap: float | None = None,
        max_tile_skip: int | None = None,
        checks_per_scan: int | None = None,
    ) -> None:
        self.viddexa_ranker = ViddexaRanker(context_classifier)
        self.borderline_margin = borderline_margin
        self.crop_expansion = crop_expansion
        self.rescue_enabled = rescue_enabled
        self.settings = settings or default_vision_settings()
        resolved_overlap = (
            float(config.RESCUE_TILE_OVERLAP) if tile_overlap is None else tile_overlap
        )
        resolved_max_skip = (
            int(config.RESCUE_MAX_TILE_SKIP) if max_tile_skip is None else max_tile_skip
        )
        self.checks_per_scan = (
            int(config.RESCUE_CHECKS_PER_SCAN) if checks_per_scan is None else checks_per_scan
        )
        self.tracker = tracker or CandidateTracker()
        self.threshold_policy = ThresholdPolicy.from_settings(self.settings)
        self.candidate_verifier = CandidateVerifier(
            local_detector,
            threshold_policy=self.threshold_policy,
            tile_input_size=self.settings.detector.tile_input_size,
            enabled=self.settings.recheck.enabled,
        )
        self.visual_decision_engine = _VisualDecisionEngine(
            self.threshold_policy, borderline_margin=self.borderline_margin
        )
        self.scheduler = TileScheduler(
            self.settings,
            rows=rescue_rows,
            columns=rescue_columns,
            overlap=resolved_overlap,
            max_skip=resolved_max_skip,
            pin_followup_checks=pin_followup_checks,
        )
        self.scan_planner = ScanPlanner(
            self.scheduler,
            self.tracker,
            self.viddexa_ranker,
            crop_expansion=self.crop_expansion,
        )

    def evaluate(
        self,
        detection: PrimaryDetection,
        captured_frame: CaptureFrame,
        *,
        monitor_index: int = 1,
        scan_plan: ScanPlan | None = None,
        is_active_monitor: bool = True,
        prepared_frame: FramePreprocessor | None = None,
    ) -> VisualViolationDecision:
        """Return a candidate decision without retaining image pixels."""

        prepared = prepared_frame or FramePreprocessor(captured_frame)
        prepared.require_frame(captured_frame)
        frame_sequence = captured_frame.sequence
        primary_assessment = self.visual_decision_engine.assess_primary(
            detection.primary
        )
        result = self._initial_result(detection, primary_assessment)

        plan = scan_plan
        if plan is None:
            active = self.tracker.active_track(monitor_index)
            if active is not None:
                original = captured_frame.image
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
                self.scheduler.remember_plan(monitor_index, plan)
        if plan is not None and plan.mode == "focused" and plan.roi is not None:
            focused = self._evaluate_focused(
                result,
                captured_frame,
                monitor_index,
                plan.roi,
                frame_sequence,
                prepared,
            )
            return self._finalize_decision(
                focused, captured_frame, monitor_index, frame_sequence
            )

        if primary_assessment.strong is not None:
            decided = self._confirm_primary_candidate(
                result,
                captured_frame,
                primary_assessment.strong,
                confirmed_source="nudenet_roi",
                candidate_source="anatomy_candidate",
                fallback=self._strong_primary_result(
                    result, captured_frame, threshold=primary_assessment.threshold
                ),
                prepared=prepared,
            )
            return self._finalize_decision(
                decided, captured_frame, monitor_index, frame_sequence
            )

        assessment = self.visual_decision_engine.assess(detection.evidence)
        if assessment.strong is not None:
            chosen = assessment.strong
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
                prepared=prepared,
            )
            return self._finalize_decision(
                decided, captured_frame, monitor_index, frame_sequence
            )

        borderline = assessment.proposal
        if borderline is None:
            borderline_candidate = self.visual_decision_engine.borderline_candidate(
                detection.primary
            )
            if borderline_candidate is None:
                base = self._with_metadata(
                    result,
                    source="nudenet_none",
                    classification=VisualViolationClassification.CLEAR,
                )
            else:
                base = self._evaluate_borderline(
                    result, captured_frame, borderline_candidate, prepared
                )
                if base["classification"] is VisualViolationClassification.VIOLATION:
                    return self._finalize_decision(
                        base, captured_frame, monitor_index, frame_sequence
                    )
        else:
            threshold = self.threshold_policy.strong(
                borderline.label, borderline.model
            )
            if threshold is None:
                raise RuntimeError("proposal evidence has no strong threshold")
            base = self._evaluate_borderline(
                result,
                captured_frame,
                BorderlineCandidate(borderline, threshold),
                prepared,
            )
            if base["classification"] is VisualViolationClassification.VIOLATION:
                return self._finalize_decision(
                    base, captured_frame, monitor_index, frame_sequence
                )

        if plan is None:
            plan = self.scan_planner.prepare_scan(
                captured_frame,
                monitor_index,
                is_active_monitor=is_active_monitor,
                prepared_frame=prepared,
            )
        decided = self._evaluate_rescue(
            base, captured_frame, monitor_index, plan=plan, prepared=prepared
        )
        return self._finalize_decision(
            decided, captured_frame, monitor_index, frame_sequence
        )

    @staticmethod
    def _initial_result(
        detection: PrimaryDetection,
        assessment: PrimaryAssessment,
    ) -> dict[str, Any]:
        """Serialize a pure primary assessment into working metadata."""

        checkpoints = [
            {
                "class": item.label,
                "score": item.confidence,
                "box": None if item.bbox is None else list(item.bbox),
            }
            for item in detection.primary
        ]
        strongest = assessment.strong
        threshold = assessment.threshold
        result = {
            "classification": assessment.classification,
            "reason": (
                f"{strongest.label} (score {strongest.confidence:.2f}, "
                f"threshold {threshold:.2f})"
                if strongest is not None
                else ""
            ),
            "label": None if strongest is None else strongest.label,
            "confidence": 0.0 if strongest is None else strongest.confidence,
            "box": None if strongest is None or strongest.bbox is None else list(strongest.bbox),
            "check_points": checkpoints,
            "evidence": [evidence_to_dict(item) for item in detection.evidence],
        }
        return result

    def _confirm_primary_candidate(
        self,
        result: dict[str, Any],
        captured_frame: CaptureFrame,
        evidence: ViolationEvidence,
        *,
        confirmed_source: str,
        candidate_source: str,
        fallback: dict[str, Any],
        prepared: FramePreprocessor,
    ) -> dict[str, Any]:
        """Confirm primary visual evidence on an original-resolution ROI.

        Temporal confirmation still happens on a later fresh frame. Viddexa is
        not consulted: this is visual evidence, not viewing purpose.
        """

        label = evidence.label
        score = evidence.confidence
        box = evidence.bbox
        if (
            not self.candidate_verifier.enabled
            or self.candidate_verifier.detector is None
            or not isinstance(box, (list, tuple))
        ):
            return fallback
        threshold = self.threshold_policy.strong(label, evidence.model)
        if threshold is None:
            return fallback
        roi = self._evaluate_borderline(
            result,
            captured_frame,
            BorderlineCandidate(evidence, threshold),
            prepared,
        )
        if roi["classification"] is VisualViolationClassification.VIOLATION:
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
        captured_frame: CaptureFrame,
        borderline: BorderlineCandidate,
        prepared: FramePreprocessor,
    ) -> dict[str, Any]:
        """Recheck a borderline box on the original-resolution crop."""

        label = borderline.evidence.label
        score = borderline.evidence.confidence
        threshold = borderline.threshold
        box = borderline.evidence.bbox
        base = self._with_metadata(
            result,
            source="nudenet_borderline",
            nudenet_label=label,
            nudenet_score=score,
            threshold=threshold,
            classification=VisualViolationClassification.UNCERTAIN,
        )
        original = captured_frame.image
        model = original
        if (
            not self.candidate_verifier.enabled
            or self.candidate_verifier.detector is None
            or not isinstance(box, (list, tuple))
            or not isinstance(original, np.ndarray)
            or not hasattr(model, "shape")
        ):
            return base

        recheck = self.candidate_verifier.context_recheck(
            prepared, box, model_shape=model.shape, expansion=self.crop_expansion
        )
        if recheck is None:
            return base
        base["region"] = recheck.region

        hit = recheck.hit
        base["local_check_points"] = []
        base["local_box"] = None if hit is None or hit.bbox is None else list(hit.bbox)
        if hit is None:
            return base

        confirmed_label = hit.label
        confidence = float(hit.confidence)
        confirmed_threshold = threshold_for_label(str(confirmed_label))
        base.update(
            {
                "classification": VisualViolationClassification.VIOLATION,
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
        captured_frame: CaptureFrame,
        monitor_index: int,
        plan: ScanPlan | None = None,
        prepared: FramePreprocessor | None = None,
    ) -> dict[str, Any]:
        """Check priority tiles. Viddexa only orders them; it never vetoes."""

        prepared = prepared or FramePreprocessor(captured_frame)
        original = prepared.original
        if (
            not self.rescue_enabled
            or self.candidate_verifier.detector is None
            or not isinstance(original, np.ndarray)
        ):
            return base

        tiles = self.scheduler.tiles_for(monitor_index, prepared)
        if not tiles:
            return base

        tile_indexes = list(plan.tile_indexes) if plan is not None else []
        if not tile_indexes:
            ranked = self.scheduler.ranked_tiles(tiles)
            tile_indexes = [item.index for item in ranked[: max(1, self.checks_per_scan)]]

        ranking_payload = [
            {"index": tile.index, "priority": tile.priority_score}
            for tile in self.scheduler.ranked_tiles(list(tiles))
        ]
        base["tile_ranking"] = ranking_payload

        checked: set[int] = set()
        decided = base
        for tile_index in tile_indexes:
            tile_state = next((item for item in tiles if item.index == tile_index), None)
            if tile_state is None:
                continue
            crop = prepared.crop_xyxy(tile_state.region)
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
            self.scheduler.advance_tile(monitor_index, tile_index, len(tiles))
            decided["rescue_tile_index"] = tile_index
            decided["rescue_region"] = tile_state.region
            decided["context_label"] = context_label
            decided["context_score"] = float(context_score)
            decided["context_scores"] = context_scores or None

            hit = self.candidate_verifier.strong_hit(crop, frame_sequence=captured_frame.sequence)
            decided["local_box"] = None if hit is None or hit.bbox is None else list(hit.bbox)
            if hit is not None:
                self.scheduler.pin_tile(monitor_index, tile_index)
                label = hit.label
                confidence = float(hit.confidence)
                threshold = threshold_for_label(str(label))
                decided.update(
                    {
                        "classification": VisualViolationClassification.VIOLATION,
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
                self.scheduler.mark_checked(monitor_index, tiles, checked)
                return decided

            if (
                plan is not None
                and plan.subdivide
                and tile_state.context_score >= 0.6
                and tile_state.change_score >= 0.4
            ):
                subdivided = self._evaluate_subtiles(
                    decided, prepared, tile_state, monitor_index
                )
                if subdivided["classification"] is VisualViolationClassification.VIOLATION:
                    checked.add(tile_index)
                    self.scheduler.mark_checked(monitor_index, tiles, checked)
                    return subdivided

        self.scheduler.mark_checked(monitor_index, tiles, checked)
        return decided

    def reset(self) -> None:
        """Clear pinned and ranking state after an intervention or bypass."""

        self.tracker.reset()
        self.scheduler.reset()

    def _evaluate_focused(
        self,
        result: dict[str, Any],
        captured_frame: CaptureFrame,
        monitor_index: int,
        roi: Region,
        frame_sequence: int,
        prepared: FramePreprocessor,
    ) -> dict[str, Any]:
        original = captured_frame.image
        base = self._with_metadata(
            result,
            source="focused_roi",
            region=roi,
            classification=VisualViolationClassification.CLEAR,
        )
        if self.candidate_verifier.detector is None or not isinstance(original, np.ndarray):
            return base
        recheck = self.candidate_verifier.region_recheck(prepared, roi)
        if recheck is None:
            return base
        hit = recheck.hit
        base["local_box"] = None if hit is None or hit.bbox is None else list(hit.bbox)
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
                "classification": VisualViolationClassification.VIOLATION,
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
        prepared: FramePreprocessor,
        tile_state: TileState,
        monitor_index: int,
    ) -> dict[str, Any]:
        del monitor_index
        if self.candidate_verifier.detector is None:
            return base
        top_subtile = self.viddexa_ranker.top_subtile(prepared, tile_state.region)
        if top_subtile is None:
            return base
        hit = self.candidate_verifier.strong_hit(top_subtile.image, frame_sequence=prepared.frame.sequence)
        base["local_box"] = None if hit is None or hit.bbox is None else list(hit.bbox)
        if hit is None:
            return base
        label = hit.label
        confidence = float(hit.confidence)
        base.update(
            {
                "classification": VisualViolationClassification.VIOLATION,
                "reason": (
                    f"coarse-to-fine found {label} score {confidence:.2f}"
                ),
                "label": label,
                "confidence": confidence,
                "source": "subtile",
                "region": top_subtile.region,
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
        captured_frame: CaptureFrame,
        monitor_index: int,
        frame_sequence: int,
    ) -> VisualViolationDecision:
        plan = self.scheduler.last_plan(monitor_index)
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
        if decided["classification"] is VisualViolationClassification.VIOLATION:
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
        return self.visual_decision_engine.finalize(
            decided,
            frame_sequence=frame_sequence,
            monitor_index=monitor_index,
        )

    def rescue_status(self, monitor_index: int) -> dict[str, int | None]:
        """Return scalar scheduling state without exposing any image data."""

        return self.scheduler.rescue_status(monitor_index)

    def _strong_primary_result(
        self,
        result: dict[str, Any],
        captured_frame: CaptureFrame,
        *,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        box = result.get("box")
        region: Region | None = None
        original = captured_frame.image
        if isinstance(box, (list, tuple)) and original is not None:
            region = map_box_to_original(
                box,
                original.shape,
                original.shape,
            )
        label = result.get("label")
        if threshold is None:
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
        captured_frame: CaptureFrame,
        evidence: ViolationEvidence | None,
    ) -> dict[str, Any]:
        if evidence is None:
            return self._strong_primary_result(result, captured_frame)
        box = None if evidence.bbox is None else list(evidence.bbox)
        payload = dict(result)
        payload.update(
            {
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
            classification = result["classification"]
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
                "classification": classification,
                "evidence": result["evidence"],
            }
        )
        return result
