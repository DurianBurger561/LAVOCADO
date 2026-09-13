"""Batch runner with cancel. Keeps completed rows when cancelled."""

from __future__ import annotations

from threading import Event, Lock
from typing import Any, Callable

from developer.benchmark.configs import BenchmarkConfig
from developer.benchmark.dataset import BenchmarkDataset
from developer.benchmark.engine import evaluate_sample, session_for
from developer.benchmark.inference_cache import InferenceCache
from developer.benchmark.results import BenchmarkRun, finalize_run, new_run, save_run
from developer.benchmark.session import BenchmarkSession


ProgressCallback = Callable[[dict[str, Any]], None]


class BenchmarkRunner:
    def __init__(
        self,
        dataset: BenchmarkDataset,
        configs: list[BenchmarkConfig],
        *,
        cache: InferenceCache | None = None,
        session_factory: Callable[..., BenchmarkSession] = session_for,
        session_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.dataset = dataset
        self.configs = list(configs)
        self.cache = cache or InferenceCache(dataset.cache_dir)
        self.session_factory = session_factory
        self.session_kwargs = dict(session_kwargs or {})
        self.cancel_event = Event()
        self._lock = Lock()
        self.run: BenchmarkRun | None = None
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

    def start(self, on_progress: ProgressCallback | None = None) -> BenchmarkRun:
        run = new_run(self.dataset, self.configs)
        self.run = run
        samples = list(self.dataset.samples)
        self._set_progress(status="running", sample_count=len(samples), config_count=len(self.configs))
        for config_index, config in enumerate(self.configs, start=1):
            if self.cancel_event.is_set():
                break
            session = self.session_factory(
                config,
                cache=self.cache,
                **self.session_kwargs,
            )
            label = (
                f"{config.detector} {config.full_input_size} "
                f"{config.context_model or 'off'}"
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
            session.reset()
        run.cancelled = self.cancel_event.is_set()
        finalize_run(run)
        save_run(self.dataset, run)
        self._set_progress(status="cancelled" if run.cancelled else "completed")
        if on_progress is not None:
            on_progress(self.progress())
        return run

    def _set_progress(self, **fields: Any) -> None:
        with self._lock:
            self._progress.update(fields)
