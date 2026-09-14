"""Product Block/Allow metrics. Unlabelled and excluded samples are omitted."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from statistics import mean as statistics_mean
from statistics import median as statistics_median
from typing import Any

from developer.benchmark.configs import TARGET_FULL_PROTECTION_PIPELINE
from developer.benchmark.dataset import EXPECTED_ALLOW, EXPECTED_BLOCK
from developer.benchmark.ranking import summarize_ranking
from developer.benchmark.tags import (
    NON_PORNOGRAPHIC_PURPOSE,
    PURPOSE_SUBTAGS,
    RECALL_TAGS,
    TAG_LABELS,
)

OUTCOME_TP = "tp"
OUTCOME_TN = "tn"
OUTCOME_FP = "fp"
OUTCOME_FN = "fn"
OUTCOME_UNLABELLED = "unlabelled"
OUTCOME_EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class ConfusionCounts:
    tp: int = 0
    tn: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def total(self) -> int:
        return self.tp + self.tn + self.fp + self.fn

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Metric:
    """One named scalar; missing measurements remain unavailable, not zero."""

    name: str
    value: float | None
    unit: str

    def difference_from(self, baseline: Metric) -> float | None:
        if self.name != baseline.name or self.unit != baseline.unit:
            raise ValueError("cannot compare different metrics")
        if self.value is None or baseline.value is None:
            return None
        return self.value - baseline.value


def outcome_for(expected: str | None, predicted: str | None, *, excluded: bool) -> str:
    if excluded:
        return OUTCOME_EXCLUDED
    if expected not in {EXPECTED_BLOCK, EXPECTED_ALLOW}:
        return OUTCOME_UNLABELLED
    if predicted not in {EXPECTED_BLOCK, EXPECTED_ALLOW}:
        return OUTCOME_UNLABELLED
    if expected == EXPECTED_BLOCK and predicted == EXPECTED_BLOCK:
        return OUTCOME_TP
    if expected == EXPECTED_BLOCK and predicted == EXPECTED_ALLOW:
        return OUTCOME_FN
    if expected == EXPECTED_ALLOW and predicted == EXPECTED_ALLOW:
        return OUTCOME_TN
    return OUTCOME_FP


def counts_from_outcomes(outcomes: Iterable[str]) -> ConfusionCounts:
    tp = tn = fp = fn = 0
    for outcome in outcomes:
        if outcome == OUTCOME_TP:
            tp += 1
        elif outcome == OUTCOME_TN:
            tn += 1
        elif outcome == OUTCOME_FP:
            fp += 1
        elif outcome == OUTCOME_FN:
            fn += 1
    return ConfusionCounts(tp=tp, tn=tn, fp=fp, fn=fn)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def metric_bundle(counts: ConfusionCounts) -> dict[str, Any]:
    total = counts.total
    accuracy = _ratio(counts.tp + counts.tn, total)
    failure_rate = _ratio(counts.fp + counts.fn, total)
    recall = _ratio(counts.tp, counts.tp + counts.fn)
    precision = _ratio(counts.tp, counts.tp + counts.fp)
    fnr = _ratio(counts.fn, counts.tp + counts.fn)
    fpr = _ratio(counts.fp, counts.fp + counts.tn)
    return {
        **counts.to_dict(),
        "total": total,
        "accuracy": accuracy,
        "failure_rate": failure_rate,
        "recall": recall,
        "precision": precision,
        "fnr": fnr,
        "fpr": fpr,
    }


def summarize_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    target: str = TARGET_FULL_PROTECTION_PIPELINE,
) -> dict[str, Any]:
    eligible = [
        row
        for row in rows
        if not bool(row.get("excluded"))
        and row.get("expected") in {EXPECTED_BLOCK, EXPECTED_ALLOW}
        and row.get("predicted") in {EXPECTED_BLOCK, EXPECTED_ALLOW}
    ]
    outcomes = [
        outcome_for(
            str(row["expected"]),
            str(row["predicted"]),
            excluded=False,
        )
        for row in eligible
    ]
    counts = counts_from_outcomes(outcomes)
    latencies = [
        float(row["total_ms"])
        for row in eligible
        if isinstance(row.get("total_ms"), (int, float))
    ]
    payload = {
        "target": target,
        **metric_bundle(counts),
        "mean_latency_ms": mean(latencies) if latencies else None,
        "p95_latency_ms": percentile(latencies, 0.95) if latencies else None,
        "tag_metrics": tag_metrics(eligible),
    }
    ranking = summarize_ranking(rows)
    if ranking is not None:
        payload["ranking"] = ranking
    return payload


def summarize_context_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Score Context Policy actions separately from image Block/Allow metrics."""

    samples = list(rows)
    labelled = [
        row for row in samples if not row.get("excluded") and row.get("expected")
    ]
    correct = sum(row.get("outcome") == "correct" for row in labelled)
    latencies = [
        float(row["total_ms"])
        for row in samples
        if isinstance(row.get("total_ms"), (int, float))
    ]
    return {
        "target": "context_policy",
        "sample_count": len(samples),
        "labelled_count": len(labelled),
        "correct": correct,
        "incorrect": len(labelled) - correct,
        "accuracy": _ratio(correct, len(labelled)),
        "mean_latency_ms": mean(latencies) if latencies else None,
        "p95_latency_ms": percentile(latencies, 0.95) if latencies else None,
    }


def summarize_detector_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Detector Only summary. Never computes product Block/Allow FP/FN."""

    samples = list(rows)
    detections: list[dict[str, Any]] = []
    latencies: list[float] = []
    for row in samples:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        items = raw.get("detections") or []
        if isinstance(items, list):
            detections.extend(item for item in items if isinstance(item, dict))
        if isinstance(raw.get("inference_ms"), (int, float)):
            latencies.append(float(raw["inference_ms"]))
    return {
        "target": "detector_only",
        "sample_count": len(samples),
        "detection_count": len(detections),
        "mean_latency_ms": mean(latencies) if latencies else None,
        "p95_latency_ms": percentile(latencies, 0.95) if latencies else None,
        "detections": [
            {
                "label": item.get("class") or item.get("label"),
                "confidence": item.get("score"),
                "box": item.get("box"),
            }
            for item in detections
        ],
    }


def tag_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        tags = row.get("tags") or []
        if isinstance(tags, str):
            tag_list = [tags]
        else:
            tag_list = [str(tag) for tag in tags]
        for tag in tag_list:
            grouped.setdefault(tag, []).append(row)
    payload: dict[str, Any] = {}
    for tag, items in grouped.items():
        expected_allow = [
            item for item in items if item.get("expected") == EXPECTED_ALLOW
        ]
        expected_block = [
            item for item in items if item.get("expected") == EXPECTED_BLOCK
        ]
        allow_rate = _ratio(
            sum(1 for item in expected_allow if item.get("predicted") == EXPECTED_ALLOW),
            len(expected_allow),
        )
        recall = _ratio(
            sum(1 for item in expected_block if item.get("predicted") == EXPECTED_BLOCK),
            len(expected_block),
        )
        entry = {
            "label": TAG_LABELS.get(tag, tag),
            "count": len(items),
            "allow_rate": allow_rate,
            "recall": recall,
        }
        payload[tag] = entry
    purpose_rows = grouped.get(NON_PORNOGRAPHIC_PURPOSE, [])
    payload["non_pornographic_purpose_allow_rate"] = _ratio(
        sum(
            1
            for item in purpose_rows
            if item.get("expected") == EXPECTED_ALLOW
            and item.get("predicted") == EXPECTED_ALLOW
        ),
        sum(1 for item in purpose_rows if item.get("expected") == EXPECTED_ALLOW),
    )
    for tag in sorted(PURPOSE_SUBTAGS | RECALL_TAGS):
        payload.setdefault(
            tag,
            {
                "label": TAG_LABELS.get(tag, tag),
                "count": len(grouped.get(tag, [])),
                "allow_rate": None,
                "recall": None,
            },
        )
    return payload


def mean(values: Iterable[float]) -> float:
    """Shared arithmetic mean for every Benchmark Lab runner."""

    return float(statistics_mean(values))


def median(values: Iterable[float]) -> float:
    """Shared median for every Benchmark Lab runner."""

    return float(statistics_median(values))


def percentile(values: Iterable[float], fraction: float) -> float:
    """Shared linearly interpolated percentile, with one definition of p95."""

    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("cannot summarize an empty sample")
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be within 0..1")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight
