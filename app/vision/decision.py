"""Classify primary-detector evidence. Viddexa only ranks tiles."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from app.platforms.capture.models import CaptureFrame
from app.settings.schema import VisionSettings, default_vision_settings
from app.vision.candidate_verifier import CandidateVerifier
from app.vision.detectors.base import PrimaryDetector
from app.vision.evidence import evidence_from_confidence
from app.vision.preprocessor import FramePreprocessor
from app.vision.primary_detector_set import PrimaryDetection
from app.vision.regions import Region, map_box_to_original
from app.vision.scan_planner import ScanPlanner
from app.vision.scheduler import ScanPlan, TileScheduler
from app.vision.tracking import CandidateTracker, box_to_region
from app.vision.verification_flow import VerificationFlow
from app.vision.viddexa_ranker import ContextSensor, ViddexaRanker
from app.vision.violation_policy import (
    ThresholdPolicy,
    ViolationEvidence,
    ViolationEvidenceType,
    VisualViolationClassification,
    VisualViolationDecision,
    evidence_type_for_label,
)
from app.vision.visual_decision import (
    BorderlineCandidate,
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
        local_detector: PrimaryDetector | None = None,
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
        self.verification_flow = VerificationFlow(
            settings=self.settings,
            verifier=self.candidate_verifier,
            scheduler=self.scheduler,
            ranker=self.viddexa_ranker,
            tracker=self.tracker,
            threshold_policy=self.threshold_policy,
            crop_expansion=self.crop_expansion,
            rescue_enabled=self.rescue_enabled,
            checks_per_scan=self.checks_per_scan,
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
        result = self.visual_decision_engine.draft_from_assessment(
            detection.evidence, primary_assessment
        )

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
            focused = self.verification_flow.evaluate_focused(
                result,
                monitor_index,
                plan.roi,
                prepared,
            )
            return self._finalize_decision(
                focused, monitor_index, frame_sequence
            )

        if primary_assessment.strong is not None:
            decided = self.verification_flow.confirm_primary_candidate(
                result,
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
            decided = self.verification_flow.confirm_primary_candidate(
                result,
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
                base = self.visual_decision_engine.with_metadata(
                    result,
                    source="nudenet_none",
                    classification=VisualViolationClassification.CLEAR,
                )
            else:
                base = self.verification_flow.evaluate_borderline(
                    result, borderline_candidate, prepared
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
            base = self.verification_flow.evaluate_borderline(
                result,
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
        decided = self.verification_flow.evaluate_rescue(
            base, monitor_index, plan=plan, prepared=prepared
        )
        return self._finalize_decision(
            decided, monitor_index, frame_sequence
        )

    def reset(self) -> None:
        """Clear tracked and scheduled work after intervention or bypass."""

        self.tracker.reset()
        self.scheduler.reset()

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
                    score,
                    label,
                    policy=self.threshold_policy,
                    model=self._model_for_label(decided),
                ),
                evidence_type=evidence_type_for_label(label),
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
            threshold = self.threshold_policy.strong(
                str(label), self._model_for_label(result)
            )
        return self.visual_decision_engine.with_metadata(
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
            model=evidence.model,
            confidence=evidence.confidence,
            box=evidence.bbox,
            evidence=result.evidence or (evidence,),
        )
        decided = self._strong_primary_result(
            payload,
            captured_frame,
            threshold=self.threshold_policy.strong(evidence.label, evidence.model),
        )
        decided.source = (
            "yolo_sexual_act"
            if evidence.evidence_type is ViolationEvidenceType.SEXUAL_ACT
            else f"{evidence.model}_full"
        )
        return decided

    @staticmethod
    def _model_for_label(result: VisualDecisionDraft) -> str | None:
        if result.model is not None:
            return result.model
        match = next(
            (item for item in result.evidence if item.label == result.label), None
        )
        return None if match is None else match.model
