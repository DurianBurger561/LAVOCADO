"""One dispatch table for Developer Benchmark Lab's dataset and tool runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from developer.benchmark.configs import (
    BENCHMARK_TARGETS,
    TARGET_CONTEXT_POLICY,
    TARGET_DETECTOR,
    TARGET_FULL_PROTECTION_PIPELINE,
    TARGET_VISION_PIPELINE,
)
from developer.benchmark.contracts import BenchmarkRequest
from developer.benchmark.inference_cache import InferenceCache
from developer.benchmark.jobs import LabProcessJob
from developer.benchmark.runner import BenchmarkRunner


@dataclass(frozen=True, slots=True)
class BenchmarkDefinition:
    id: str
    label: str
    execution: str
    tool_kind: str | None = None
    tool_mode: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


DEFINITIONS = (
    BenchmarkDefinition("capture", "Capture", "tool", "capture"),
    BenchmarkDefinition("preprocessing", "Preprocessing", "tool", "diagnostic", "preprocessor"),
    BenchmarkDefinition(TARGET_DETECTOR, "Detector", "dataset"),
    BenchmarkDefinition("region_ranking", "Region Ranking", "tool", "diagnostic", "ranker_signal"),
    BenchmarkDefinition(TARGET_VISION_PIPELINE, "Vision Pipeline", "dataset"),
    BenchmarkDefinition(TARGET_CONTEXT_POLICY, "Context Policy", "dataset"),
    BenchmarkDefinition(TARGET_FULL_PROTECTION_PIPELINE, "Full Pipeline", "dataset"),
)


class BenchmarkRegistry:
    """Route UI and CLI work to the same product-backed runner implementations."""

    def __init__(self) -> None:
        self._definitions = {item.id: item for item in DEFINITIONS}
        dataset_ids = {item.id for item in DEFINITIONS if item.execution == "dataset"}
        if dataset_ids != BENCHMARK_TARGETS:
            raise RuntimeError("Benchmark registry and config targets disagree")

    def categories(self) -> list[dict[str, str | None]]:
        return [item.to_dict() for item in DEFINITIONS]

    def runner(
        self,
        request: BenchmarkRequest,
        *,
        cache: InferenceCache | None = None,
        session_kwargs: dict[str, Any] | None = None,
    ) -> BenchmarkRunner:
        for config in request.configs:
            entry = self._definitions.get(config.benchmark_target)
            if entry is None or entry.execution != "dataset":
                raise ValueError(f"Unknown dataset benchmark: {config.benchmark_target}")
        return BenchmarkRunner(request, cache=cache, session_kwargs=session_kwargs)

    def tool_job(
        self, kind: str, arguments: list[str], data_dir: Path
    ) -> LabProcessJob:
        if kind not in {"capture", "diagnostic", "stability"}:
            raise ValueError(f"Unknown Lab tool: {kind}")
        return LabProcessJob(kind, arguments, data_dir)
