"""Threshold sweep using cached raw detections. Policy-only rerun."""

from __future__ import annotations

from typing import Any, Iterable

from app.settings.schema import merge_vision_settings
from developer.benchmark.configs import BenchmarkConfig
from developer.benchmark.dataset import BenchmarkDataset, eligible_for_metrics
from developer.benchmark.engine import policy_only_rerun
from developer.benchmark.inference_cache import InferenceCache, RawInferenceResult, cache_key
from developer.benchmark.metrics import summarize_rows
from developer.benchmark.session import (
    BenchmarkSession,
    load_bgr_image,
    model_revision_for,
    sample_hash_for,
)

DEFAULT_STRONG = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)
DEFAULT_PROPOSAL = (0.35, 0.40, 0.45)


def sweep_thresholds(
    dataset: BenchmarkDataset,
    config: BenchmarkConfig,
    *,
    strong_values: Iterable[float] = DEFAULT_STRONG,
    proposal_values: Iterable[float] | None = None,
    cache: InferenceCache | None = None,
    session: BenchmarkSession | None = None,
) -> list[dict[str, Any]]:
    cache = cache or InferenceCache(dataset.cache_dir)
    base_session = session or BenchmarkSession(config, cache=cache)
    rows: list[dict[str, Any]] = []
    raw_by_sample: dict[str, RawInferenceResult] = {}
    for sample in dataset.samples:
        if not eligible_for_metrics(sample) and sample.expected is None and not sample.excluded:
            path = dataset.resolve_path(sample)
            image = load_bgr_image(path)
            digest = sample_hash_for(path, sample)
            raw_by_sample[sample.id] = base_session.run_detector_only(
                sample, image, sample_hash=digest
            )
            del image
            continue
        path = dataset.resolve_path(sample)
        digest = sample_hash_for(path, sample)
        key = cache_key(
            sample_hash=digest,
            model_id=config.detector,
            model_revision=model_revision_for(config.detector),
            input_size=config.full_input_size,
            region_id="full",
            tile_geometry=config.cache_geometry(),
        )
        cached = cache.get(key)
        if cached is None:
            image = load_bgr_image(path)
            cached = base_session.run_detector_only(sample, image, sample_hash=digest)
            del image
        raw_by_sample[sample.id] = cached

    strong_list = [float(value) for value in strong_values]
    if proposal_values is None:
        proposal_list: list[float | None] = [None]
    else:
        proposal_list = [float(value) for value in proposal_values]
    for strong, proposal in iter_sweep_pairs(strong_list, proposal_list):
        patched = _with_thresholds(config, strong=strong, proposal=proposal)
        sweep_session = BenchmarkSession(patched, cache=cache, detector=base_session.detector)
        evaluated = []
        for sample in dataset.samples:
            raw = raw_by_sample.get(sample.id)
            if raw is None:
                continue
            evaluated.append(policy_only_rerun(sweep_session, dataset, sample, raw))
        summary = summarize_rows(evaluated)
        rows.append(
            {
                "strong": strong,
                "proposal": proposal,
                **summary,
            }
        )
    return rows


def iter_sweep_pairs(
    strong_values: Iterable[float],
    proposal_values: Iterable[float | None],
) -> list[tuple[float, float | None]]:
    """Drop meaningless pairs. Proposal must stay strictly below strong."""

    pairs: list[tuple[float, float | None]] = []
    for strong in strong_values:
        strong_v = float(strong)
        for proposal in proposal_values:
            if proposal is None:
                pairs.append((strong_v, None))
                continue
            proposal_v = float(proposal)
            if proposal_v >= strong_v:
                continue
            pairs.append((strong_v, proposal_v))
    return pairs


def _with_thresholds(
    config: BenchmarkConfig,
    *,
    strong: float,
    proposal: float | None,
) -> BenchmarkConfig:
    settings = config.vision_settings().to_dict()
    tables = settings.get("thresholds") or {}
    for model_name, labels in list(tables.items()):
        if not isinstance(labels, dict):
            continue
        updated = {}
        for label, pair in labels.items():
            current = dict(pair) if isinstance(pair, dict) else {}
            current["strong"] = strong
            if proposal is not None:
                current["proposal"] = float(proposal)
            updated[label] = current
        tables[model_name] = updated
    settings["thresholds"] = tables
    merged = merge_vision_settings(config.vision_settings(), settings)
    return BenchmarkConfig(
        id=f"{config.id}-s{strong}",
        benchmark_target=config.benchmark_target,
        detector=config.detector,
        context_model=config.context_model,
        full_input_size=config.full_input_size,
        tile_input_size=config.tile_input_size,
        tile_rows=config.tile_rows,
        tile_columns=config.tile_columns,
        tile_overlap=config.tile_overlap,
        checks_per_scan=config.checks_per_scan,
        threshold_profile=f"sweep-{strong}",
        settings=merged.to_dict(),
    )
