"""Coordinate local ROI and rescue verification without owning classification."""

from __future__ import annotations

from app.settings.schema import VisionSettings
from app.vision.candidate_verifier import CandidateVerifier
from app.vision.preprocessor import FramePreprocessor
from app.vision.regions import Region
from app.vision.scheduler import ScanPlan, TileScheduler
from app.vision.tiles import TileState
from app.vision.tracking import CandidateTracker
from app.vision.viddexa_ranker import ViddexaRanker
from app.vision.violation_policy import (
    ThresholdPolicy,
    ViolationEvidence,
    VisualViolationClassification,
)
from app.vision.visual_decision import (
    BorderlineCandidate,
    VisualDecisionDraft,
    VisualDecisionEngine,
)


class VerificationFlow:
    """Apply local rechecks and tile scheduling to a typed decision draft."""

    def __init__(
        self,
        *,
        settings: VisionSettings,
        verifier: CandidateVerifier,
        scheduler: TileScheduler,
        ranker: ViddexaRanker,
        tracker: CandidateTracker,
        threshold_policy: ThresholdPolicy,
        crop_expansion: float,
        rescue_enabled: bool,
        checks_per_scan: int,
    ) -> None:
        self.settings = settings
        self.verifier = verifier
        self.scheduler = scheduler
        self.ranker = ranker
        self.tracker = tracker
        self.threshold_policy = threshold_policy
        self.crop_expansion = crop_expansion
        self.rescue_enabled = rescue_enabled
        self.checks_per_scan = checks_per_scan

    def confirm_primary_candidate(
        self,
        result: VisualDecisionDraft,
        evidence: ViolationEvidence,
        *,
        confirmed_source: str,
        candidate_source: str,
        fallback: VisualDecisionDraft,
        prepared: FramePreprocessor,
    ) -> VisualDecisionDraft:
        """Require an original-resolution ROI hit when local recheck is enabled."""

        box = evidence.bbox
        if not self.verifier.enabled or self.verifier.detector is None or box is None:
            return fallback
        threshold = self.threshold_policy.strong(evidence.label, evidence.model)
        if threshold is None:
            return fallback
        roi = self.evaluate_borderline(
            result, BorderlineCandidate(evidence, threshold), prepared
        )
        if roi.classification is VisualViolationClassification.VIOLATION:
            roi.source = confirmed_source
            return roi
        if not roi.recheck_performed:
            return fallback
        roi.source = candidate_source
        roi.label = evidence.label
        roi.model = evidence.model
        roi.confidence = evidence.confidence
        return roi

    def evaluate_borderline(
        self,
        result: VisualDecisionDraft,
        borderline: BorderlineCandidate,
        prepared: FramePreprocessor,
    ) -> VisualDecisionDraft:
        """Recheck a candidate on pixels cropped from the canonical full frame."""

        base = VisualDecisionEngine.with_metadata(
            result,
            source="nudenet_borderline",
            threshold=borderline.threshold,
            classification=VisualViolationClassification.UNCERTAIN,
        )
        if (
            not self.verifier.enabled
            or self.verifier.detector is None
            or borderline.evidence.bbox is None
        ):
            return base
        recheck = self.verifier.context_recheck(
            prepared,
            borderline.evidence.bbox,
            model_shape=prepared.original.shape,
            expansion=self.crop_expansion,
        )
        if recheck is None:
            return base
        base.region = recheck.region
        base.recheck_performed = True
        hit = recheck.hit
        if hit is None:
            return base
        base.classification = VisualViolationClassification.VIOLATION
        base.label = hit.label
        base.model = hit.model
        base.confidence = hit.confidence
        base.source = "nudenet_roi"
        base.threshold = self.threshold_policy.strong(hit.label, hit.model)
        return base

    def evaluate_rescue(
        self,
        base: VisualDecisionDraft,
        monitor_index: int,
        *,
        plan: ScanPlan | None,
        prepared: FramePreprocessor,
    ) -> VisualDecisionDraft:
        """Check priority tiles; Viddexa affects order but never vetoes a hit."""

        if not self.rescue_enabled or self.verifier.detector is None:
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
        for tile in batch.selected:
            context_scores = dict(tile.context_scores)
            if context_scores:
                context_label, context_score = max(
                    context_scores.items(), key=lambda item: item[1]
                )
            else:
                context_label, context_score = "none", 0.0
            decided.rescue_tile_index = tile.index
            decided.context_label = context_label
            decided.context_score = float(context_score)
            model_frame = prepared.prepare_region(
                tile.region, self.settings.detector.tile_input_size
            )
            if model_frame is None:
                continue
            checked.add(tile.index)
            hit = self.verifier.strong_hit(model_frame)
            self.scheduler.record_rescue_attempt(
                monitor_index, tile.index, confirmed=hit is not None
            )
            if hit is not None:
                decided.classification = VisualViolationClassification.VIOLATION
                decided.label = hit.label
                decided.model = hit.model
                decided.confidence = hit.confidence
                decided.source = "rescue_tile"
                decided.region = tile.region
                decided.threshold = self.threshold_policy.strong(hit.label, hit.model)
                self.scheduler.mark_checked(monitor_index, batch.tiles, checked)
                return decided
            if (
                plan is not None
                and plan.subdivide
                and tile.context_score >= 0.6
                and tile.change_score >= 0.4
            ):
                subdivided = self._evaluate_subtiles(decided, prepared, tile)
                if subdivided.classification is VisualViolationClassification.VIOLATION:
                    self.scheduler.mark_checked(monitor_index, batch.tiles, checked)
                    return subdivided
        self.scheduler.mark_checked(monitor_index, batch.tiles, checked)
        return decided

    def evaluate_focused(
        self,
        result: VisualDecisionDraft,
        monitor_index: int,
        roi: Region,
        prepared: FramePreprocessor,
    ) -> VisualDecisionDraft:
        base = VisualDecisionEngine.with_metadata(
            result,
            source="focused_roi",
            region=roi,
            classification=VisualViolationClassification.CLEAR,
        )
        if self.verifier.detector is None:
            return base
        recheck = self.verifier.region_recheck(prepared, roi)
        if recheck is None:
            return base
        base.region = roi
        hit = recheck.hit
        if hit is None:
            track = self.tracker.active_track(monitor_index)
            if track is not None:
                self.tracker.mark_miss(track, decay=self.settings.temporal.decay)
            base.source = "focused_miss"
            return base
        base.classification = VisualViolationClassification.VIOLATION
        base.label = hit.label
        base.model = hit.model
        base.confidence = hit.confidence
        base.source = "focused_roi"
        base.threshold = self.threshold_policy.strong(hit.label, hit.model)
        return base

    def _evaluate_subtiles(
        self,
        base: VisualDecisionDraft,
        prepared: FramePreprocessor,
        tile: TileState,
    ) -> VisualDecisionDraft:
        if self.verifier.detector is None:
            return base
        subtile = self.ranker.top_subtile(prepared, tile.region)
        if subtile is None:
            return base
        model_frame = prepared.prepare_region(
            subtile.region, self.settings.detector.tile_input_size
        )
        if model_frame is None:
            return base
        hit = self.verifier.strong_hit(model_frame)
        if hit is None:
            return base
        base.classification = VisualViolationClassification.VIOLATION
        base.label = hit.label
        base.model = hit.model
        base.confidence = hit.confidence
        base.source = "subtile"
        base.region = subtile.region
        base.threshold = self.threshold_policy.strong(hit.label, hit.model)
        return base
