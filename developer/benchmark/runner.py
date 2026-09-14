"""Batch runner with cancel. Keeps completed rows when cancelled."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock
from time import perf_counter, process_time
from typing import Any

import psutil

from developer.benchmark.configs import TARGET_CONTEXT_POLICY
from developer.benchmark.contracts import BenchmarkRequest
from developer.benchmark.engine import evaluate_sample, session_for
from developer.benchmark.inference_cache import InferenceCache
from developer.benchmark.results import BenchmarkResult, finalize_run, new_run, save_run
from developer.benchmark.session import BenchmarkSession

ProgressCallback = Callable[[dict[str, Any]], None]


class BenchmarkRunner:
    def __init__(
        self,
        request: BenchmarkRequest,
        *,
        cache: InferenceCache | None = None,
        session_factory: Callable[..., BenchmarkSession] = session_for,
        session_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.request = request
        self.dataset = request.dataset
        self.configs = list(request.configs)
        self.cache = cache or InferenceCache(self.dataset.cache_dir)
        self.session_factory = session_factory
        self.session_kwargs = dict(session_kwargs or {})
        self.cancel_event = Event()
        self._lock = Lock()
        self.run: BenchmarkResult | None = None
        self._progress: dict[str, Any] = {
            "status": "idle",
            "config_index": 0,
            "config_count": len(self.configs),
            "sample_index": 0,
            "sample_count": 0,
            "current": "",
        }

    def request_cancel(self) -> None:
        self.cancel_event.set()

    def progress(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._progress)

    def start(self, on_progress: ProgressCallback | None = None) -> BenchmarkResult:
        run = new_run(self.dataset, self.configs)
        self.run = run
        samples = list(self.dataset.samples)
        process = psutil.Process()
        resources: dict[str, dict[str, float | int]] = {}
        self._set_progress(status="running", sample_count=len(samples), config_count=len(self.configs))
        for config_index, config in enumerate(self.configs, start=1):
            if self.cancel_event.is_set():
                break
            wall_started = perf_counter()
            cpu_started = process_time()
            peak_ram = int(process.memory_info().rss)
            session = self.session_factory(
                config,
                cache=self.cache,
                **self.session_kwargs,
            )
            label = (
                "Context Policy"
                if config.benchmark_target == TARGET_CONTEXT_POLICY
                else f"{config.detector} {config.full_input_size} {config.context_model or 'off'}"
            )
            for sample_index, sample in enumerate(samples, start=1):
                if self.cancel_event.is_set():
                    break
                self._set_progress(
                    status="running",
                    config_index=config_index,
                    sample_index=sample_index,
                    current=label,
                )
                if on_progress is not None:
                    on_progress(self.progress())
                row = evaluate_sample(session, self.dataset, sample)
                run.rows.append(row)
                peak_ram = max(peak_ram, int(process.memory_info().rss))
            session.reset()
            wall_seconds = max(0.0, perf_counter() - wall_started)
            cpu_seconds = max(0.0, process_time() - cpu_started)
            resources[config.id] = {
                "cpu_percent": (
                    0.0 if wall_seconds == 0 else round(cpu_seconds / wall_seconds * 100, 1)
                ),
                "ram_bytes": peak_ram,
            }
        run.cancelled = self.cancel_event.is_set()
        finalize_run(run)
        for config_id, measurements in resources.items():
            run.summaries.setdefault(config_id, {}).update(measurements)
        save_run(self.dataset, run)
        self._set_progress(status="cancelled" if run.cancelled else "completed")
        if on_progress is not None:
            on_progress(self.progress())
        return run

    def _set_progress(self, **fields: Any) -> None:
        with self._lock:
            self._progress.update(fields)
