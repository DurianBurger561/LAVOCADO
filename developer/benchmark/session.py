"""Isolated Benchmark session. Reuses product Vision/Decision; never Overlay."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

import numpy as np
from PIL import Image

from app.context.models import ContextPolicyAction, ContextPolicyResult
from app.diagnostics import DiagnosticsStore
from app.platforms.capture.models import CaptureFrame, Rect
from app.protection_runtime import ProtectionRuntime
from app.settings.schema import VisionSettings
from app.vision.change_scheduler import ChangeScheduler
from app.vision.context.factory import load_context_ranker
from app.vision.decision import DecisionEngine
from app.vision.detectors.base import to_violation_evidence
from app.vision.detectors.factory import load_primary_bundle
from app.vision.model_manifest import (
    NUDENET_640M_SHA256,
    YOLO11_NSFW_SMALL_REVISION,
)
from app.vision.pipeline import VisionPipeline
from app.vision.preprocessor import FramePreprocessor
from app.vision.temporal import TemporalVerifier
from app.vision.violation_policy import (
    ThresholdPolicy,
    ViolationEvidence,
    VisualViolationClassification,
    VisualViolationDecision,
    activate_threshold_policy,
    active_threshold_policy,
)
from developer.benchmark.configs import (
    TARGET_CONTEXT_POLICY,
    TARGET_DETECTOR,
    TARGET_FULL_PROTECTION_PIPELINE,
    BenchmarkConfig,
)
from developer.benchmark.context_fixture import context_policy_for_sample
from developer.benchmark.dataset import (
    EXPECTED_ALLOW,
    EXPECTED_BLOCK,
    BenchmarkSample,
    hash_file,
)
from developer.benchmark.inference_cache import (
    InferenceCache,
    RawInferenceResult,
    cache_key,
)
from developer.benchmark.metrics import outcome_for
from developer.benchmark.ranking import measure_ranking

_POLICY_LOCK = Lock()


@contextmanager
def isolated_threshold_policy(policy: ThresholdPolicy) -> Iterator[None]:
    """Apply a session-local threshold table without leaking to other users."""

    with _POLICY_LOCK:
        previous = active_threshold_policy()
        activate_threshold_policy(policy)
        try:
            yield
        finally:
            activate_threshold_policy(previous)


def load_bgr_image(path) -> np.ndarray:
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    return np.ascontiguousarray(rgb[:, :, ::-1])


def captured_frame_from_bgr(bgr: np.ndarray, *, sequence: int = 1) -> CaptureFrame:
    return CaptureFrame(
        image=np.ascontiguousarray(bgr),
        monitor_id="benchmark",
        sequence=sequence,
        changed_regions=(Rect(0, 0, bgr.shape[1], bgr.shape[0]),),
        backend="local_image",
    )


def model_revision_for(detector_name: str) -> str:
    if str(detector_name).startswith("yolo"):
        return YOLO11_NSFW_SMALL_REVISION
    return NUDENET_640M_SHA256


def detections_payload(evidence: list[ViolationEvidence]) -> list[dict[str, Any]]:
    payload = []
    for item in evidence:
        payload.append(
            {
                "class": item.label,
                "score": float(item.confidence),
                "box": None if item.bbox is None else list(item.bbox),
                "model": item.model,
            }
        )
    return payload


def evidence_from_payload(
    detections: list[dict[str, Any]],
    model_id: str,
    *,
    frame_sequence: int,
) -> list[ViolationEvidence]:
    return to_violation_evidence(
        detections, model=model_id, frame_sequence=frame_sequence
    )


class CachedPrimaryDetector:
    """Replay cached detections. Does not run a vision model."""

    def __init__(self, detections: list[dict[str, Any]], model_id: str) -> None:
        self.name = model_id
        self.model_variant = model_id
        self._raw = list(detections)

    def detect(
        self, frame: np.ndarray, *, input_size: int, frame_sequence: int
    ) -> list[ViolationEvidence]:
        del frame, input_size
        return evidence_from_payload(
            self._raw, self.name, frame_sequence=frame_sequence
        )


class BenchmarkSession:
    """One isolated benchmark stack using production vision and policy contracts."""

    def __init__(
        self,
        config: BenchmarkConfig,
        *,
        detector: Any | None = None,
        context_ranker: Any | None = None,
        pipeline: VisionPipeline | None = None,
        cache: InferenceCache | None = None,
        detector_factory: Callable[..., Any] = load_primary_bundle,
        context_factory: Callable[..., Any] = load_context_ranker,
        data_dir: Any | None = None,
    ) -> None:
        self.config = config
        self.settings: VisionSettings = config.vision_settings()
        self.cache = cache
        self._threshold_policy = ThresholdPolicy.from_settings(self.settings)
        if config.benchmark_target == TARGET_CONTEXT_POLICY:
            self.detector = None
            self.decision_engine = None
            self.pipeline = None
            return
        if config.benchmark_target == TARGET_DETECTOR:
            if detector is None and pipeline is not None:
                detector = pipeline.primary_detectors.primary
            if detector is None:
                detector = detector_factory(
                    self.settings.detector.primary,
                    full_input_size=self.settings.detector.full_input_size,
                    data_dir=data_dir,
                ).primary
            self.detector = detector
            self.decision_engine = None
            self.pipeline = None
            return
        if pipeline is not None:
            self.pipeline = pipeline
            self.detector = pipeline.primary_detectors.primary
            self.decision_engine = pipeline.decision_engine
        else:
            if detector is None:
                bundle = detector_factory(
                    self.settings.detector.primary,
                    full_input_size=self.settings.detector.full_input_size,
                    data_dir=data_dir,
                )
                detector = bundle.primary
            self.detector = detector
            use_context_ranking = (
                self.settings.context.model != "off"
                and self.settings.context.tile_ranking
                and self.settings.tiles.enabled
            )
            if context_ranker is None and use_context_ranking:
                context_ranker = context_factory(
                    self.settings.context.model,
                    enabled=True,
                    data_dir=data_dir,
                )
            context_sensor = None
            if context_ranker is not None and getattr(context_ranker, "name", None) != "off":
                context_sensor = context_ranker
            self.decision_engine = DecisionEngine(
                context_sensor,
                detector,
                settings=self.settings,
                rescue_enabled=self.settings.tiles.enabled,
                rescue_rows=self.settings.tiles.rows,
                rescue_columns=self.settings.tiles.columns,
                crop_expansion=self.settings.recheck.crop_expansion,
                tile_overlap=self.settings.tiles.overlap,
                max_tile_skip=self.settings.tiles.max_skip,
                checks_per_scan=self.settings.tiles.checks_per_scan,
                borderline_margin=self.settings.recheck.proposal_margin,
                pin_followup_checks=max(0, self.settings.temporal.window_size - 1),
            )
            self.pipeline = VisionPipeline(
                detector,
                self.decision_engine,
                full_input_size=self.settings.detector.full_input_size,
            )

    def reset(self) -> None:
        if self.pipeline is not None:
            self.pipeline.reset()

    def run_detector_only(
        self,
        sample: BenchmarkSample,
        image: np.ndarray,
        *,
        sample_hash: str,
    ) -> RawInferenceResult:
        if self.detector is None:
            raise ValueError("Context Policy Benchmark has no detector")
        key = cache_key(
            sample_hash=sample_hash,
            model_id=self.config.detector,
            model_revision=model_revision_for(self.config.detector),
            input_size=self.config.full_input_size,
            region_id="full",
            tile_geometry=self.config.cache_geometry(),
        )
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        started = time.perf_counter()
        preprocess_ms = 0.0
        evidence = self.detector.detect(
            image, input_size=self.config.full_input_size, frame_sequence=1
        )
        detections = detections_payload(evidence)
        inference_ms = (time.perf_counter() - started) * 1000
        raw = RawInferenceResult(
            sample_id=sample.id,
            model_id=self.config.detector,
            model_revision=model_revision_for(self.config.detector),
            input_size=self.config.full_input_size,
            region_id="full",
            detections=detections,
            preprocess_ms=preprocess_ms,
            inference_ms=inference_ms,
            postprocess_ms=0.0,
        )
        if self.cache is not None:
            self.cache.put(key, raw)
        return raw

    def run_full_pipeline(
        self,
        sample: BenchmarkSample,
        image: np.ndarray,
        *,
        sample_hash: str,
    ) -> dict[str, Any]:
        """Run Context Policy first, then the production vision/temporal path."""

        context_result = self.context_protection_result(sample)
        if context_result is not None:
            return context_result
        raw = self.run_detector_only(sample, image, sample_hash=sample_hash)
        return self.evaluate_policy(sample, image, raw)

    def context_protection_result(
        self, sample: BenchmarkSample
    ) -> dict[str, Any] | None:
        """Return an immediate final action when Context Policy gates Vision."""

        policy = self._policy_result(sample)
        if policy.action is ContextPolicyAction.NORMAL:
            return None
        return self._context_protection_row(sample, policy)

    def run_vision_pipeline(
        self,
        sample: BenchmarkSample,
        image: np.ndarray,
        *,
        sample_hash: str,
    ) -> dict[str, Any]:
        """Evaluate one visual frame without Context Policy or temporal gating."""

        raw = self.run_detector_only(sample, image, sample_hash=sample_hash)
        return self.evaluate_policy(sample, image, raw)

    def run_context_policy(self, sample: BenchmarkSample) -> dict[str, Any]:
        """Score typed Context Policy outcomes without opening an image."""

        started = time.perf_counter()
        policy = self._policy_result(sample)
        predicted = policy.action.value
        expected = sample.expected_policy
        outcome = (
            "excluded"
            if sample.excluded
            else "unlabelled"
            if expected is None
            else "correct"
            if expected == predicted
            else "incorrect"
        )
        return {
            "sample_id": sample.id,
            "config_id": self.config.id,
            "expected": expected,
            "predicted": predicted,
            "excluded": sample.excluded,
            "tags": sorted(sample.tags),
            "outcome": outcome,
            "correct": outcome == "correct",
            "total_ms": (time.perf_counter() - started) * 1000,
            "vision_called": False,
            "context_summary": self._context_summary(policy),
        }

    def evaluate_policy(
        self,
        sample: BenchmarkSample,
        image: np.ndarray,
        raw: RawInferenceResult,
    ) -> dict[str, Any]:
        """Replay cached evidence through the current product VisionPipeline."""

        if self.pipeline is None or self.decision_engine is None:
            raise ValueError("Context Policy Benchmark has no vision pipeline")
        policy = (
            self._policy_result(sample)
            if self.config.benchmark_target == TARGET_FULL_PROTECTION_PIPELINE
            else None
        )
        if policy is not None and policy.action is not ContextPolicyAction.NORMAL:
            return self._context_protection_row(sample, policy)

        self.reset()
        cached = CachedPrimaryDetector(raw.detections, self.config.detector)
        previous_local = self.decision_engine.candidate_verifier.detector
        self.decision_engine.candidate_verifier.detector = cached
        replay_pipeline = VisionPipeline(
            cached,
            self.decision_engine,
            full_input_size=self.settings.detector.full_input_size,
        )
        full_protection = self.config.benchmark_target == TARGET_FULL_PROTECTION_PIPELINE
        repeats = self.settings.temporal.window_size if full_protection else 1
        runtime = self._protection_runtime(replay_pipeline) if full_protection else None
        decided: VisualViolationDecision | None = None
        confirmed = False
        temporal_history: tuple[bool, ...] = ()
        fresh_frames = 0
        started = time.perf_counter()
        try:
            with isolated_threshold_policy(self._threshold_policy):
                for index in range(repeats):
                    frame = captured_frame_from_bgr(image, sequence=index + 1)
                    fresh_frames += 1
                    if runtime is not None:
                        outcome = runtime.scan_monitor(
                            frame,
                            1,
                            is_active_monitor=True,
                            scan_started=time.perf_counter(),
                        )
                        decided = outcome.decision or decided
                        confirmed = outcome.confirmed
                        temporal_history = outcome.temporal_history
                        if confirmed:
                            break
                    else:
                        prepared = FramePreprocessor(frame)
                        plan = replay_pipeline.prepare_scan(
                            frame, 1, prepared_frame=prepared
                        )
                        decided = replay_pipeline.evaluate(
                            frame,
                            monitor_index=1,
                            scan_plan=plan,
                            prepared_frame=prepared,
                        )
        finally:
            self.decision_engine.candidate_verifier.detector = previous_local
        if decided is None:
            raise RuntimeError("Benchmark vision pipeline did not evaluate a frame")
        ranking = measure_ranking(
            self.decision_engine.viddexa_ranker.classifier,
            image,
            raw.detections,
            rows=self.config.tile_rows,
            columns=self.config.tile_columns,
            overlap=self.config.tile_overlap,
            context_model=self.config.context_model,
        )
        total_ms = (time.perf_counter() - started) * 1000
        blocking = (
            confirmed
            if full_protection
            else decided.classification is VisualViolationClassification.VIOLATION
        )
        predicted = EXPECTED_BLOCK if blocking else EXPECTED_ALLOW
        outcome = outcome_for(sample.expected, predicted, excluded=sample.excluded)
        strongest = _strongest_detection(raw.detections)
        return {
            "sample_id": sample.id,
            "config_id": self.config.id,
            "expected": sample.expected,
            "predicted": predicted,
            "excluded": sample.excluded,
            "tags": sorted(sample.tags),
            "outcome": outcome,
            "correct": outcome in {"tp", "tn"},
            "total_ms": total_ms,
            "vision_called": True,
            "temporal_summary": {
                "confirmed": confirmed,
                "fresh_frames": fresh_frames,
                "history": list(temporal_history),
            } if full_protection else None,
            "detector_summary": {
                "model": self.config.detector,
                "detections": raw.detections,
                "best_label": None if strongest is None else strongest.get("class"),
                "best_confidence": None if strongest is None else strongest.get("score"),
                "inference_ms": raw.inference_ms,
            },
            "context_summary": {
                "policy_action": None if policy is None else policy.action.value,
                "model": self.config.context_model,
                "label": decided.context_label,
                "score": decided.context_score,
                "scores": None,
                "rescue_tile_index": decided.rescue_tile_index,
                "ranking": ranking,
            },
            "ranking": ranking,
            "decision_summary": {
                "classification": decided.classification.value,
                "reason_codes": list(decided.reason_codes),
                "label": decided.label,
                "confidence": decided.confidence,
                "threshold": decided.threshold,
                "evidence": [
                    {
                        "evidence_type": item.evidence_type.value,
                        "label": item.label,
                        "confidence": item.confidence,
                    }
                    for item in decided.evidence
                ],
            },
        }

    def _policy_result(self, sample: BenchmarkSample) -> ContextPolicyResult:
        policy, context = context_policy_for_sample(sample)
        return policy.evaluate(context)

    @staticmethod
    def _context_summary(policy: ContextPolicyResult) -> dict[str, str]:
        return {
            "policy_action": policy.action.value,
            "application_action": policy.app_action.value,
            "website_action": policy.website_action.value,
        }

    def _context_protection_row(
        self,
        sample: BenchmarkSample,
        policy: ContextPolicyResult,
    ) -> dict[str, Any]:
        predicted = (
            EXPECTED_BLOCK
            if policy.action is ContextPolicyAction.FORCE_BLOCK
            else EXPECTED_ALLOW
        )
        outcome = outcome_for(sample.expected, predicted, excluded=sample.excluded)
        return {
            "sample_id": sample.id,
            "config_id": self.config.id,
            "expected": sample.expected,
            "predicted": predicted,
            "excluded": sample.excluded,
            "tags": sorted(sample.tags),
            "outcome": outcome,
            "correct": outcome in {"tp", "tn"},
            "total_ms": 0.0,
            "vision_called": False,
            "temporal_summary": None,
            "detector_summary": {},
            "context_summary": self._context_summary(policy),
            "decision_summary": {},
        }

    def _protection_runtime(self, pipeline: VisionPipeline) -> ProtectionRuntime:
        temporal = self.settings.temporal
        scheduler = ChangeScheduler(
            change_ratio_threshold=self.settings.scan.change_sensitivity,
            adaptive=self.settings.scan.adaptive,
            candidate_followup_checks=max(0, temporal.window_size - 1),
        )
        diagnostics = DiagnosticsStore(
            model_variant=self.config.detector,
            inference_resolution=self.config.full_input_size,
            context_model=self.config.context_model or "off",
            context_status="disabled",
        )
        return ProtectionRuntime(
            pipeline,
            self.decision_engine,
            scheduler,
            diagnostics,
            lambda: TemporalVerifier(
                temporal.window_size,
                temporal.min_fresh_hits,
                evidence_threshold=temporal.evidence_threshold,
                decay=temporal.decay,
                confirmation=temporal.confirmation,
            ),
            time.perf_counter,
        )


def _strongest_detection(detections: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = []
    for item in detections:
        try:
            scored.append((float(item.get("score") or 0.0), item))
        except (TypeError, ValueError):
            continue
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[0])[1]


def sample_hash_for(path, sample: BenchmarkSample) -> str:
    if sample.content_hash:
        return sample.content_hash
    return hash_file(path)
