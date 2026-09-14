"""Benchmark engine: Detector Only and Full Protection Pipeline."""

from __future__ import annotations

from typing import Any

from developer.benchmark.configs import (
    TARGET_CONTEXT_POLICY,
    TARGET_DETECTOR,
    TARGET_FULL_PROTECTION_PIPELINE,
    TARGET_VISION_PIPELINE,
    BenchmarkConfig,
)
from developer.benchmark.dataset import BenchmarkDataset, BenchmarkSample
from developer.benchmark.inference_cache import InferenceCache, RawInferenceResult
from developer.benchmark.session import (
    BenchmarkSession,
    load_bgr_image,
    sample_hash_for,
)


def evaluate_sample(
    session: BenchmarkSession,
    dataset: BenchmarkDataset,
    sample: BenchmarkSample,
) -> dict[str, Any]:
    if session.config.benchmark_target == TARGET_CONTEXT_POLICY:
        payload = session.run_context_policy(sample)
        payload["target"] = TARGET_CONTEXT_POLICY
        return payload
    if session.config.benchmark_target == TARGET_FULL_PROTECTION_PIPELINE:
        context_result = session.context_protection_result(sample)
        if context_result is not None:
            context_result["target"] = TARGET_FULL_PROTECTION_PIPELINE
            return context_result
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
        if session.config.benchmark_target == TARGET_VISION_PIPELINE:
            payload = session.run_vision_pipeline(sample, image, sample_hash=digest)
        elif session.config.benchmark_target == TARGET_FULL_PROTECTION_PIPELINE:
            payload = session.run_full_pipeline(sample, image, sample_hash=digest)
        else:
            raise ValueError(f"Unknown benchmark target: {session.config.benchmark_target}")
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
