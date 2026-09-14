"""Isolated Benchmark session. Reuses product Vision/Decision; never Overlay."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

import numpy as np
from PIL import Image

from app.platforms.capture.models import CaptureFrame
from app.settings.schema import VisionSettings
from app.vision.context.factory import load_context_ranker
from app.vision.decision import DecisionEngine
from app.vision.detectors.base import to_violation_evidence
from app.vision.detectors.factory import load_primary_bundle
from app.vision.model_assets import (
    NUDENET_640M_SHA256,
    YOLO11_NSFW_SMALL_REVISION,
)
from app.vision.pipeline import VisionPipeline
from app.vision.primary_detector_set import PrimaryDetection
from app.vision.violation_policy import (
    ThresholdPolicy,
    ViolationEvidence,
    activate_threshold_policy,
    active_threshold_policy,
)
from developer.benchmark.configs import BenchmarkConfig
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


def captured_frame_from_bgr(bgr: np.ndarray, *, max_edge: int, sequence: int = 1) -> CaptureFrame:
    del max_edge
    return CaptureFrame(
        image=np.ascontiguousarray(bgr),
        monitor_id="benchmark",
        sequence=sequence,
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
    """One independent Vision/Decision stack. Does not touch Protection runtime."""

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
            if context_ranker is None:
                context_ranker = context_factory(
                    self.settings.context.model,
                    enabled=self.settings.context.model != "off",
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
            )
            self.pipeline = VisionPipeline(
                detector,
                self.decision_engine,
                full_input_size=self.settings.detector.full_input_size,
            )

    def reset(self) -> None:
        reset = getattr(self.pipeline, "reset", None)
        if callable(reset):
            reset()

    def run_detector_only(
        self,
        sample: BenchmarkSample,
        image: np.ndarray,
        *,
        sample_hash: str,
    ) -> RawInferenceResult:
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
        detections = detections_payload(list(evidence or []))
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
        raw = self.run_detector_only(sample, image, sample_hash=sample_hash)
        return self.evaluate_policy(sample, image, raw)

    def evaluate_policy(
        self,
        sample: BenchmarkSample,
        image: np.ndarray,
        raw: RawInferenceResult,
    ) -> dict[str, Any]:
        """Re-run Decision on cached detections. Never re-infers the primary model."""

        self.reset()
        cached = CachedPrimaryDetector(raw.detections, self.config.detector)
        previous_local = self.decision_engine.candidate_verifier.detector
        self.decision_engine.candidate_verifier.detector = cached
        repeats = max(1, int(self.settings.temporal.window_size))
        decided: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            with isolated_threshold_policy(self._threshold_policy):
                for index in range(repeats):
                    frame = captured_frame_from_bgr(
                        image,
                        max_edge=self.settings.detector.full_input_size,
                        sequence=index + 1,
                    )
                    primary_evidence = tuple(
                        cached.detect(
                            image,
                            input_size=self.config.full_input_size,
                            frame_sequence=frame.sequence,
                        )
                    )
                    decided = self.decision_engine.evaluate(
                        PrimaryDetection.from_primary(primary_evidence),
                        frame,
                        monitor_index=1,
                    )
        finally:
            self.decision_engine.candidate_verifier.detector = previous_local
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
        from app.vision.violation_policy import VisualViolationClassification

        predicted = (
            EXPECTED_BLOCK
            if decided.classification is VisualViolationClassification.VIOLATION
            else EXPECTED_ALLOW
        )
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
            "detector_summary": {
                "model": self.config.detector,
                "detections": raw.detections,
                "best_label": None if strongest is None else strongest.get("class"),
                "best_confidence": None if strongest is None else strongest.get("score"),
                "inference_ms": raw.inference_ms,
            },
            "context_summary": {
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
