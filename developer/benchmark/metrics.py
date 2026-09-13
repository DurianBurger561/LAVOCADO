"""Product Block/Allow metrics. Unlabelled and excluded samples are omitted."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from developer.benchmark.dataset import EXPECTED_ALLOW, EXPECTED_BLOCK
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


def summarize_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
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
    return {
        **metric_bundle(counts),
        "mean_latency_ms": _mean(latencies),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "tag_metrics": tag_metrics(eligible),
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


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]
