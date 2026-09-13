"""Annotation helpers. Unknown is not a ground-truth value."""

from __future__ import annotations

from typing import Any, Iterable

from developer.benchmark.dataset import (
    ALLOWED_EXPECTED,
    BenchmarkDataset,
    BenchmarkSample,
    update_sample,
    update_samples,
)
from developer.benchmark.tags import CANONICAL_TAGS, normalize_tag

FILTERS = ("all", "unlabelled", "block", "allow", "excluded")


def filter_samples(
    dataset: BenchmarkDataset,
    *,
    status: str = "all",
    tags: Iterable[str] | None = None,
) -> list[BenchmarkSample]:
    wanted_status = str(status or "all").strip().lower()
    if wanted_status not in FILTERS:
        wanted_status = "all"
    required_tags = {slug for slug in (normalize_tag(tag) or "" for tag in (tags or [])) if slug}
    selected: list[BenchmarkSample] = []
    for sample in dataset.samples:
        if wanted_status == "unlabelled" and sample.expected is not None:
            continue
        if wanted_status == "block" and sample.expected != "block":
            continue
        if wanted_status == "allow" and sample.expected != "allow":
            continue
        if wanted_status == "excluded" and not sample.excluded:
            continue
        if required_tags and not required_tags.issubset(sample.tags):
            continue
        selected.append(sample)
    return selected


def mark_block(dataset: BenchmarkDataset, sample_id: str) -> BenchmarkSample:
    return update_sample(dataset, sample_id, expected="block")


def mark_allow(dataset: BenchmarkDataset, sample_id: str) -> BenchmarkSample:
    return update_sample(dataset, sample_id, expected="allow")


def toggle_exclude(dataset: BenchmarkDataset, sample_id: str) -> BenchmarkSample:
    sample = dataset.sample_by_id(sample_id)
    return update_sample(dataset, sample_id, excluded=not sample.excluded)


def mark_selected(
    dataset: BenchmarkDataset,
    sample_ids: Iterable[str],
    *,
    expected: str | None = None,
    excluded: bool | None = None,
) -> int:
    kwargs: dict[str, Any] = {}
    if expected is not None:
        if expected not in ALLOWED_EXPECTED:
            raise ValueError("Selected ground truth must be block or allow")
        kwargs["expected"] = expected
    if excluded is not None:
        kwargs["excluded"] = excluded
    return update_samples(dataset, sample_ids, **kwargs)


def available_tags() -> tuple[str, ...]:
    return tuple(sorted(CANONICAL_TAGS))
