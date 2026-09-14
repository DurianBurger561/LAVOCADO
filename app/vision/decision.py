"""Classify primary-detector evidence. Viddexa only ranks tiles."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

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
    ThresholdPolicy,
    ViolationEvidence,
    ViolationEvidenceType,
    VisualViolationClassification,
    VisualViolationDecision,
    threshold_for_label,
)
from app.vision.visual_decision import (
    BorderlineCandidate,
    PrimaryAssessment,
    VisualDecisionDraft,
)
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
        borderline_margin: float | None = None,
        crop_expansion: float | None = None,
        rescue_enabled: bool | None = None,
        rescue_rows: int | None = None,
        rescue_columns: int | None = None,
        pin_followup_checks: int | None = None,
        settings: VisionSettings | None = None,
        tracker: CandidateTracker | None = None,
        tile_overlap: float | None = None,
        max_tile_skip: int | None = None,
        checks_per_scan: int | None = None,
    ) -> None:
        self.settings = settings or default_vision_settings()
        self.viddexa_ranker = ViddexaRanker(context_classifier)
        self.borderline_margin = (
            self.settings.recheck.proposal_margin
            if borderline_margin is None else borderline_margin
        )
        self.crop_expansion = (
            self.settings.recheck.crop_expansion
            if crop_expansion is None else crop_expansion
        )
        self.rescue_enabled = (
            self.settings.tiles.enabled if rescue_enabled is None else rescue_enabled
        )
        resolved_overlap = (
            self.settings.tiles.overlap if tile_overlap is None else tile_overlap
        )
        resolved_max_skip = (
            self.settings.tiles.max_skip if max_tile_skip is None else max_tile_skip
        )
        self.checks_per_scan = (
            self.settings.tiles.checks_per_scan
            if checks_per_scan is None else checks_per_scan
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
            rows=self.settings.tiles.rows if rescue_rows is None else rescue_rows,
            columns=(
                self.settings.tiles.columns
                if rescue_columns is None else rescue_columns
            ),
            overlap=resolved_overlap,
            max_skip=resolved_max_skip,
            pin_followup_checks=(
                max(0, self.settings.temporal.window_size - 1)
                if pin_followup_checks is None else pin_followup_checks
            ),
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
                prepared,
            )
            return self._finalize_decision(
                focused, monitor_index, frame_sequence
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
                decided, monitor_index, frame_sequence
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
                decided, monitor_index, frame_sequence
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
                if base.classification is VisualViolationClassification.VIOLATION:
                    return self._finalize_decision(
                        base, monitor_index, frame_sequence
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
            if base.classification is VisualViolationClassification.VIOLATION:
                return self._finalize_decision(
                    base, monitor_index, frame_sequence
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
            decided, monitor_index, frame_sequence
        )

    @staticmethod
    def _initial_result(
        detection: PrimaryDetection,
        assessment: PrimaryAssessment,
    ) -> VisualDecisionDraft:
        """Keep primary evidence typed throughout the decision chain."""

        strongest = assessment.strong
        return VisualDecisionDraft(
            classification=assessment.classification,
            evidence=detection.evidence,
            label=None if strongest is None else strongest.label,
            confidence=0.0 if strongest is None else strongest.confidence,
            box=None if strongest is None else strongest.bbox,
            threshold=assessment.threshold,
        )

    def _confirm_primary_candidate(
        self,
        result: VisualDecisionDraft,
        captured_frame: CaptureFrame,
        evidence: ViolationEvidence,
        *,
        confirmed_source: str,
        candidate_source: str,
        fallback: VisualDecisionDraft,
        prepared: FramePreprocessor,
    ) -> VisualDecisionDraft:
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
        if roi.classification is VisualViolationClassification.VIOLATION:
            roi.source = confirmed_source
            return roi
        if not roi.recheck_performed:
            return fallback
        roi.source = candidate_source
        roi.label = label
        roi.confidence = score
        return roi

    def _evaluate_borderline(
        self,
        result: VisualDecisionDraft,
        captured_frame: CaptureFrame,
        borderline: BorderlineCandidate,
        prepared: FramePreprocessor,
    ) -> VisualDecisionDraft:
        """Recheck a borderline box on the original-resolution crop."""

        threshold = borderline.threshold
        box = borderline.evidence.bbox
        base = self._with_metadata(
            result,
            source="nudenet_borderline",
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
        base.region = recheck.region
        base.recheck_performed = True

        hit = recheck.hit
        if hit is None:
            return base

        confirmed_label = hit.label
        confidence = float(hit.confidence)
        confirmed_threshold = threshold_for_label(str(confirmed_label))
        base.classification = VisualViolationClassification.VIOLATION
        base.label = confirmed_label
        base.confidence = confidence
        base.source = "nudenet_roi"
        base.threshold = confirmed_threshold
        return base

    def _evaluate_rescue(
        self,
        base: VisualDecisionDraft,
        captured_frame: CaptureFrame,
        monitor_index: int,
        plan: ScanPlan | None = None,
        prepared: FramePreprocessor | None = None,
    ) -> VisualDecisionDraft:
        """Check priority tiles. Viddexa only orders them; it never vetoes."""

        prepared = prepared or FramePreprocessor(captured_frame)
        original = prepared.original
        if (
            not self.rescue_enabled
            or self.candidate_verifier.detector is None
            or not isinstance(original, np.ndarray)
        ):
            return base

        batch = self.scheduler.rescue_batch(
            monitor_index,
            prepared,
            plan=plan,
            checks_per_scan=self.checks_per_scan,
        )
        if not batch.tiles:
            return base

        checked: set[int] = set()
        decided = base
        for tile_state in batch.selected:
            tile_index = tile_state.index
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
            decided.rescue_tile_index = tile_index
            decided.context_label = context_label
            decided.context_score = float(context_score)

            hit = self.candidate_verifier.strong_hit(crop, frame_sequence=captured_frame.sequence)
            self.scheduler.record_rescue_attempt(
                monitor_index, tile_index, confirmed=hit is not None
            )
            if hit is not None:
                label = hit.label
                confidence = float(hit.confidence)
                threshold = threshold_for_label(str(label))
                decided.classification = VisualViolationClassification.VIOLATION
                decided.label = label
                decided.confidence = confidence
                decided.source = "rescue_tile"
                decided.region = tile_state.region
                decided.threshold = threshold
                self.scheduler.mark_checked(monitor_index, batch.tiles, checked)
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
                if subdivided.classification is VisualViolationClassification.VIOLATION:
                    checked.add(tile_index)
                    self.scheduler.mark_checked(monitor_index, batch.tiles, checked)
                    return subdivided

        self.scheduler.mark_checked(monitor_index, batch.tiles, checked)
        return decided

    def reset(self) -> None:
        """Clear pinned and ranking state after an intervention or bypass."""

        self.tracker.reset()
        self.scheduler.reset()

    def _evaluate_focused(
        self,
        result: VisualDecisionDraft,
        captured_frame: CaptureFrame,
        monitor_index: int,
        roi: Region,
        prepared: FramePreprocessor,
    ) -> VisualDecisionDraft:
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
        base.region = roi
        if hit is None:
            track = self.tracker.active_track(monitor_index)
            if track is not None:
                self.tracker.mark_miss(track, decay=self.settings.temporal.decay)
            base.source = "focused_miss"
            return base
        label = hit.label
        confidence = float(hit.confidence)
        threshold = threshold_for_label(str(label))
        base.classification = VisualViolationClassification.VIOLATION
        base.label = label
        base.confidence = confidence
        base.source = "focused_roi"
        base.threshold = threshold
        return base

    def _evaluate_subtiles(
        self,
        base: VisualDecisionDraft,
        prepared: FramePreprocessor,
        tile_state: TileState,
        monitor_index: int,
    ) -> VisualDecisionDraft:
        del monitor_index
        if self.candidate_verifier.detector is None:
            return base
        top_subtile = self.viddexa_ranker.top_subtile(prepared, tile_state.region)
        if top_subtile is None:
            return base
        hit = self.candidate_verifier.strong_hit(top_subtile.image, frame_sequence=prepared.frame.sequence)
        if hit is None:
            return base
        label = hit.label
        confidence = float(hit.confidence)
        base.classification = VisualViolationClassification.VIOLATION
        base.label = label
        base.confidence = confidence
        base.source = "subtile"
        base.region = top_subtile.region
        base.threshold = threshold_for_label(str(label))
        return base

    def _finalize_decision(
        self,
        decided: VisualDecisionDraft,
        monitor_index: int,
        frame_sequence: int,
    ) -> VisualViolationDecision:
        plan = self.scheduler.last_plan(monitor_index)
        if plan is not None:
            decided.scan_mode = plan.mode
            decided.scan_interval_ms = plan.interval_ms
        label = decided.label
        score = decided.confidence
        hit_ids: set[int] = set()
        if decided.classification is VisualViolationClassification.VIOLATION:
            region = decided.region
            if region is None:
                region = box_to_region(decided.box, xywh=True)
            track = self.tracker.match_or_create(
                monitor_index=monitor_index,
                box=region,
                label=label,
                confidence=score,
                source=decided.source or "unknown",
                frame_sequence=frame_sequence,
                evidence_delta=evidence_from_confidence(
                    score, label
                ),
            )
            if track is not None:
                hit_ids.add(track.id)
                decided.track_id = track.id
                decided.track_fresh_hits = track.fresh_frame_hits
                decided.track_evidence = track.evidence_score
                decided.region = track.box
        self.tracker.mark_monitor_misses(
            monitor_index,
            hit_ids=hit_ids,
            decay=self.settings.temporal.decay,
            frame_sequence=frame_sequence,
        )
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
        result: VisualDecisionDraft,
        captured_frame: CaptureFrame,
        *,
        threshold: float | None = None,
    ) -> VisualDecisionDraft:
        box = result.box
        region: Region | None = None
        original = captured_frame.image
        if isinstance(box, (list, tuple)) and original is not None:
            region = map_box_to_original(
                box,
                original.shape,
                original.shape,
            )
        label = result.label
        if threshold is None:
            threshold = threshold_for_label(str(label))
        return self._with_metadata(
            result,
            source="nudenet_full",
            region=region,
            threshold=threshold,
            classification=VisualViolationClassification.VIOLATION,
        )

    def _violation_from_evidence(
        self,
        result: VisualDecisionDraft,
        captured_frame: CaptureFrame,
        evidence: ViolationEvidence | None,
    ) -> VisualDecisionDraft:
        if evidence is None:
            return self._strong_primary_result(result, captured_frame)
        payload = replace(
            result,
            label=evidence.label,
            confidence=evidence.confidence,
            box=evidence.bbox,
            evidence=result.evidence or (evidence,),
        )
        decided = self._strong_primary_result(payload, captured_frame)
        decided.source = (
            "yolo_sexual_act"
            if evidence.evidence_type.value == "sexual_act"
            else f"{evidence.model}_full"
        )
        return decided

    @staticmethod
    def _with_metadata(
        result: VisualDecisionDraft,
        *,
        source: str,
        region: Region | None = None,
        threshold: float | None = None,
        classification: VisualViolationClassification | None = None,
    ) -> VisualDecisionDraft:
        if classification is None:
            classification = result.classification
        return replace(
            result,
            source=source,
            region=region,
            threshold=threshold,
            context_label=None,
            context_score=None,
            rescue_tile_index=None,
            recheck_performed=False,
            classification=classification,
        )
