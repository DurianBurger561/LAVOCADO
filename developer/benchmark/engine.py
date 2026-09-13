"""Benchmark engine: Detector Only and Full Protection Pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from developer.benchmark.configs import TARGET_DETECTOR, BenchmarkConfig
from developer.benchmark.dataset import BenchmarkDataset, BenchmarkSample
from developer.benchmark.inference_cache import InferenceCache, RawInferenceResult
from developer.benchmark.session import BenchmarkSession, load_bgr_image, sample_hash_for


@dataclass
class PipelineBenchmarkResult:
    sample_id: str
    config_id: str
    expected: str | None
    predicted: str
    outcome: str
    correct: bool
    total_ms: float
    detector_summary: dict[str, Any] = field(default_factory=dict)
    context_summary: dict[str, Any] = field(default_factory=dict)
    decision_summary: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    excluded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "config_id": self.config_id,
            "expected": self.expected,
            "predicted": self.predicted,
            "outcome": self.outcome,
            "correct": self.correct,
            "total_ms": self.total_ms,
            "detector_summary": self.detector_summary,
            "context_summary": self.context_summary,
            "decision_summary": self.decision_summary,
            "tags": list(self.tags),
            "excluded": self.excluded,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PipelineBenchmarkResult:
        return cls(
            sample_id=str(payload.get("sample_id") or ""),
            config_id=str(payload.get("config_id") or ""),
            expected=payload.get("expected"),
            predicted=str(payload.get("predicted") or "allow"),
            outcome=str(payload.get("outcome") or ""),
            correct=bool(payload.get("correct")),
            total_ms=float(payload.get("total_ms") or 0.0),
            detector_summary=dict(payload.get("detector_summary") or {}),
            context_summary=dict(payload.get("context_summary") or {}),
            decision_summary=dict(payload.get("decision_summary") or {}),
            tags=list(payload.get("tags") or []),
            excluded=bool(payload.get("excluded")),
        )


def evaluate_sample(
    session: BenchmarkSession,
    dataset: BenchmarkDataset,
    sample: BenchmarkSample,
) -> dict[str, Any]:
    path = dataset.resolve_path(sample)
    image = load_bgr_image(path)
    digest = sample_hash_for(path, sample)
    try:
        if session.config.benchmark_target == TARGET_DETECTOR:
            raw = session.run_detector_only(sample, image, sample_hash=digest)
            return {
                "sample_id": sample.id,
                "config_id": session.config.id,
                "target": TARGET_DETECTOR,
                "expected": sample.expected,
                "excluded": sample.excluded,
                "tags": sorted(sample.tags),
                "raw": raw.to_dict(),
            }
        payload = session.run_full_pipeline(sample, image, sample_hash=digest)
        payload["target"] = session.config.benchmark_target
        return payload
    finally:
        del image


def policy_only_rerun(
    session: BenchmarkSession,
    dataset: BenchmarkDataset,
    sample: BenchmarkSample,
    raw: RawInferenceResult,
) -> dict[str, Any]:
    path = dataset.resolve_path(sample)
    image = load_bgr_image(path)
    try:
        return session.evaluate_policy(sample, image, raw)
    finally:
        del image


def session_for(
    config: BenchmarkConfig,
    cache: InferenceCache | None = None,
    **kwargs: Any,
) -> BenchmarkSession:
    return BenchmarkSession(config, cache=cache, **kwargs)
