"""Run a privacy-safe long-duration capture stability check."""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.platforms import create_platform_adapter
from app.platforms.capture import (
    CAPTURE_BACKEND_ENV,
    DEVELOPER_BUILD_ENV,
    CaptureError,
    CaptureFrame,
    CapturePermissionDeniedError,
    MonitorInfo,
    ScreenCaptureBackend,
)
from developer.benchmark.hardware_ipc import write_json
from developer.benchmark.metrics import median, percentile

EXIT_FAILED = 1
EXIT_PERMISSION_DENIED = 2
EXIT_INTERRUPTED = 130
PROGRESS_PREFIX = "LAVOCADO_CAPTURE_SOAK_PROGRESS "


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    """Cross-platform process resources used for leak indicators."""

    rss_bytes: int
    thread_count: int
    resource_count: int | None
    resource_kind: str | None


class ProcessSampler(Protocol):
    def snapshot(self) -> ProcessSnapshot: ...


class PsutilProcessSampler:
    """Sample resident memory, threads, and native handle/fd counts."""

    def __init__(self) -> None:
        try:
            import psutil
        except ImportError as error:
            raise RuntimeError(
                "Capture stability tests require requirements-developer.txt"
            ) from error
        self._process = psutil.Process()

    def snapshot(self) -> ProcessSnapshot:
        if hasattr(self._process, "num_handles"):
            resource_count = int(self._process.num_handles())
            resource_kind = "handles"
        elif hasattr(self._process, "num_fds"):
            resource_count = int(self._process.num_fds())
            resource_kind = "file_descriptors"
        else:
            resource_count = None
            resource_kind = None
        return ProcessSnapshot(
            rss_bytes=int(self._process.memory_info().rss),
            thread_count=int(self._process.num_threads()),
            resource_count=resource_count,
            resource_kind=resource_kind,
        )


def _timing_summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"samples": 0, "median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    return {
        "samples": len(values),
        "median_ms": round(median(values), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3),
    }


def _resource_growth(current: int | None, baseline: int | None) -> int | None:
    if current is None or baseline is None:
        return None
    return current - baseline


def _rss_slope_mib_per_hour(points: list[tuple[float, int]]) -> float:
    if len(points) < 2:
        return 0.0
    mean_time = statistics.mean(point[0] for point in points)
    mean_rss = statistics.mean(point[1] for point in points)
    denominator = sum((point[0] - mean_time) ** 2 for point in points)
    if denominator == 0:
        return 0.0
    numerator = sum(
        (elapsed - mean_time) * (rss - mean_rss)
        for elapsed, rss in points
    )
    bytes_per_second = numerator / denominator
    return bytes_per_second * 3600 / 1_048_576


def _validate_frame(frame: CaptureFrame, monitor: MonitorInfo) -> None:
    image = frame.image
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise RuntimeError("Capture returned an invalid BGR frame")
    if image.shape[:2] != (monitor.height, monitor.width):
        raise RuntimeError("Capture frame dimensions changed unexpectedly")
    if not image.flags.c_contiguous:
        raise RuntimeError("Capture returned a non-contiguous frame")
    if frame.monitor_id != monitor.id:
        raise RuntimeError("Capture returned a mismatched monitor")
    if frame.timestamp_ns < 1:
        raise RuntimeError("Capture returned an invalid timestamp")


def _next_fresh_frame(
    backend: ScreenCaptureBackend,
    monitor: MonitorInfo,
    previous_sequence: int,
    *,
    timeout_seconds: float,
    clock_ns: Callable[[], int],
    sleeper: Callable[[float], None],
) -> CaptureFrame:
    deadline = clock_ns() + int(timeout_seconds * 1_000_000_000)
    while True:
        frame = backend.get_latest_frame(monitor.id)
        if frame is None:
            raise RuntimeError("Capture backend returned no frame")
        _validate_frame(frame, monitor)
        if frame.sequence > previous_sequence:
            return frame
        if clock_ns() >= deadline:
            raise RuntimeError("Capture sequence stopped advancing")
        sleeper(0.01)


def _capture_status(backend: ScreenCaptureBackend) -> dict[str, Any]:
    status = backend.status()
    return {
        "preferred_backend": status.preferred_backend,
        "active_backend": status.active_backend,
        "fallback": status.fallback,
        "fallback_reason": status.fallback_reason,
        "healthy": status.healthy,
        "error": status.error,
        "monitor_count": status.monitor_count,
    }


def _progress_payload(
    *,
    elapsed_seconds: float,
    cycles: int,
    frames: int,
    process: ProcessSnapshot,
    capture: dict[str, Any],
) -> dict[str, Any]:
    return {
        "elapsed_seconds": round(elapsed_seconds, 1),
        "cycles": cycles,
        "frames": frames,
        "rss_mib": round(process.rss_bytes / 1_048_576, 2),
        "thread_count": process.thread_count,
        "resource_count": process.resource_count,
        "resource_kind": process.resource_kind,
        "active_backend": capture["active_backend"],
        "fallback": capture["fallback"],
    }


def soak_backend(
    backend: ScreenCaptureBackend,
    process: ProcessSampler,
    *,
    mode: str,
    duration_seconds: float,
    sample_interval: float,
    report_interval: float,
    max_stall_seconds: float,
    max_memory_growth_mib: float,
    max_resource_growth: int,
    release_grace_seconds: float = 0.25,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    cpu_clock: Callable[[], float] = time.process_time,
    sleeper: Callable[[float], None] = time.sleep,
    progress: Callable[[dict[str, Any]], None] | None = None,
    max_cycles: int | None = None,
) -> dict[str, Any]:
    """Exercise one backend and report bounded, content-free health metadata."""

    if (
        duration_seconds <= 0
        or sample_interval < 0
        or report_interval <= 0
        or max_stall_seconds <= 0
        or max_memory_growth_mib < 0
        or max_resource_growth < 0
    ):
        raise ValueError("invalid soak-test limits")

    pre_start = process.snapshot()
    running_baseline = pre_start
    running_final = pre_start
    peak_rss = pre_start.rss_bytes
    peak_threads = pre_start.thread_count
    peak_resources = pre_start.resource_count
    monitors: list[MonitorInfo] = []
    capture_latencies: list[float] = []
    frame_ages: list[float] = []
    transition_events: list[dict[str, Any]] = []
    last_sequences: dict[str, int] = {}
    cycles = 0
    frame_count = 0
    failure: tuple[str, str] | None = None
    interrupted = False
    started_ns = clock_ns()
    cpu_started = cpu_clock()
    run_finished_ns = started_ns
    cpu_finished = cpu_started
    deadline_ns = started_ns + int(duration_seconds * 1_000_000_000)
    next_report_ns = started_ns + int(report_interval * 1_000_000_000)
    previous_capture: dict[str, Any] | None = None
    rss_trend: list[tuple[float, int]] = []

    try:
        backend.start()
        monitors = backend.monitors()
        if not monitors:
            raise RuntimeError("Capture backend returned no physical displays")
        last_sequences = {monitor.id: 0 for monitor in monitors}
        running_baseline = process.snapshot()
        running_final = running_baseline
        rss_trend.append((0.0, running_baseline.rss_bytes))
        peak_rss = max(peak_rss, running_baseline.rss_bytes)
        peak_threads = max(peak_threads, running_baseline.thread_count)
        if running_baseline.resource_count is not None:
            peak_resources = max(
                peak_resources or running_baseline.resource_count,
                running_baseline.resource_count,
            )
        previous_capture = _capture_status(backend)
        started_ns = clock_ns()
        cpu_started = cpu_clock()
        deadline_ns = started_ns + int(duration_seconds * 1_000_000_000)
        next_report_ns = started_ns + int(report_interval * 1_000_000_000)

        while clock_ns() < deadline_ns and (
            max_cycles is None or cycles < max_cycles
        ):
            cycle_started_ns = clock_ns()
            for monitor in monitors:
                capture_started_ns = clock_ns()
                frame = _next_fresh_frame(
                    backend,
                    monitor,
                    last_sequences[monitor.id],
                    timeout_seconds=max_stall_seconds,
                    clock_ns=clock_ns,
                    sleeper=sleeper,
                )
                captured_ns = clock_ns()
                last_sequences[monitor.id] = frame.sequence
                capture_latencies.append(
                    (captured_ns - capture_started_ns) / 1_000_000
                )
                frame_ages.append(
                    max(0.0, (captured_ns - frame.timestamp_ns) / 1_000_000)
                )
                frame_count += 1
                frame = None

            cycles += 1
            capture = _capture_status(backend)
            if not capture["healthy"]:
                raise RuntimeError("Capture backend reported an unhealthy state")
            if previous_capture is not None and (
                capture["active_backend"] != previous_capture["active_backend"]
                or capture["fallback"] != previous_capture["fallback"]
            ) and len(transition_events) < 100:
                transition_events.append(
                    {
                        "elapsed_seconds": round(
                            (clock_ns() - started_ns) / 1_000_000_000,
                            1,
                        ),
                        "from_backend": previous_capture["active_backend"],
                        "to_backend": capture["active_backend"],
                        "fallback": capture["fallback"],
                        "fallback_reason": capture["fallback_reason"],
                    }
                )
            previous_capture = capture

            running_final = process.snapshot()
            peak_rss = max(peak_rss, running_final.rss_bytes)
            peak_threads = max(peak_threads, running_final.thread_count)
            if running_final.resource_count is not None:
                peak_resources = max(
                    peak_resources or running_final.resource_count,
                    running_final.resource_count,
                )

            now_ns = clock_ns()
            if now_ns >= next_report_ns:
                elapsed = (now_ns - started_ns) / 1_000_000_000
                rss_trend.append((elapsed, running_final.rss_bytes))
                if progress is not None:
                    progress(
                        _progress_payload(
                            elapsed_seconds=elapsed,
                            cycles=cycles,
                            frames=frame_count,
                            process=running_final,
                            capture=capture,
                        )
                    )
                next_report_ns = now_ns + int(report_interval * 1_000_000_000)

            remaining = sample_interval - (
                (clock_ns() - cycle_started_ns) / 1_000_000_000
            )
            if remaining > 0:
                sleeper(remaining)
    except CapturePermissionDeniedError as error:
        failure = ("permission_denied", type(error).__name__)
    except (CaptureError, RuntimeError, ValueError) as error:
        failure = ("capture_failed", type(error).__name__)
    except KeyboardInterrupt as error:
        interrupted = True
        failure = ("interrupted", type(error).__name__)
    finally:
        run_finished_ns = clock_ns()
        cpu_finished = cpu_clock()
        try:
            backend.stop()
        except Exception as error:  # noqa: BLE001 - backend cleanup boundary
            if failure is None:
                failure = ("cleanup_failed", type(error).__name__)
        gc.collect()
        if release_grace_seconds > 0:
            sleeper(release_grace_seconds)

    post_stop = process.snapshot()
    try:
        stopped_capture = _capture_status(backend)
        backend_released = (
            stopped_capture["active_backend"] is None
            and stopped_capture["monitor_count"] == 0
        )
    except Exception as error:  # noqa: BLE001 - backend status boundary
        stopped_capture = {}
        backend_released = False
        if failure is None:
            failure = ("cleanup_status_failed", type(error).__name__)

    elapsed_seconds = max(
        0.0,
        (run_finished_ns - started_ns) / 1_000_000_000,
    )
    if cycles:
        rss_trend.append((elapsed_seconds, running_final.rss_bytes))
    cpu_seconds = max(0.0, cpu_finished - cpu_started)
    running_growth_mib = (
        running_final.rss_bytes - running_baseline.rss_bytes
    ) / 1_048_576
    post_stop_growth_mib = (
        post_stop.rss_bytes - pre_start.rss_bytes
    ) / 1_048_576
    thread_growth = post_stop.thread_count - pre_start.thread_count
    resource_growth = _resource_growth(
        post_stop.resource_count,
        pre_start.resource_count,
    )
    threshold_failures = []
    if max(running_growth_mib, post_stop_growth_mib) > max_memory_growth_mib:
        threshold_failures.append("memory_growth")
    if resource_growth is not None and resource_growth > max_resource_growth:
        threshold_failures.append("native_resource_growth")
    if thread_growth > max_resource_growth:
        threshold_failures.append("thread_growth")
    if not backend_released:
        threshold_failures.append("backend_not_released")
    if threshold_failures and failure is None:
        failure = ("stability_threshold_exceeded", "StabilityThresholdError")

    return {
        "ok": failure is None,
        "mode": mode,
        "platform": platform.system(),
        "duration_target_seconds": duration_seconds,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "interrupted": interrupted,
        "cycles": cycles,
        "frames": frame_count,
        "monitor_count": len(monitors),
        "capture_latency": _timing_summary(capture_latencies),
        "frame_age": _timing_summary(frame_ages),
        "capture": previous_capture or stopped_capture,
        "backend_transitions": transition_events,
        "transition_events_truncated": len(transition_events) >= 100,
        "process": {
            "cpu_percent": round(
                0.0 if elapsed_seconds == 0 else cpu_seconds / elapsed_seconds * 100,
                2,
            ),
            "rss_running_baseline_mib": round(
                running_baseline.rss_bytes / 1_048_576,
                2,
            ),
            "rss_running_peak_mib": round(peak_rss / 1_048_576, 2),
            "rss_running_growth_mib": round(running_growth_mib, 2),
            "rss_trend_mib_per_hour": round(
                _rss_slope_mib_per_hour(rss_trend),
                2,
            ),
            "rss_post_stop_growth_mib": round(post_stop_growth_mib, 2),
            "thread_running_peak": peak_threads,
            "thread_post_stop_growth": thread_growth,
            "resource_kind": post_stop.resource_kind or pre_start.resource_kind,
            "resource_running_peak": peak_resources,
            "resource_post_stop_growth": resource_growth,
        },
        "release": {
            "backend_released": backend_released,
            "status_after_stop": stopped_capture,
        },
        "limits": {
            "max_stall_seconds": max_stall_seconds,
            "max_memory_growth_mib": max_memory_growth_mib,
            "max_resource_growth": max_resource_growth,
        },
        "threshold_failures": threshold_failures,
        "error": None if failure is None else failure[0],
        "error_type": None if failure is None else failure[1],
        "privacy": {
            "frames_saved": False,
            "frames_uploaded": False,
            "pixel_data_reported": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("auto", "native", "mss"),
        default="auto",
        help="capture mode to soak (default: auto)",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=3600.0,
        help="total run duration; use 28800 for an 8-hour soak (default: 3600)",
    )
    parser.add_argument("--sample-interval", type=float, default=0.75)
    parser.add_argument("--report-interval", type=float, default=60.0)
    parser.add_argument("--max-stall-seconds", type=float, default=5.0)
    parser.add_argument("--max-memory-growth-mib", type=float, default=256.0)
    parser.add_argument("--max-resource-growth", type=int, default=32)
    parser.add_argument("--result-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--progress-file", type=Path, help=argparse.SUPPRESS)
    return parser


def _print_progress(payload: dict[str, Any]) -> None:
    print(f"{PROGRESS_PREFIX}{json.dumps(payload, sort_keys=True)}", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environment = dict(os.environ)
    environment[DEVELOPER_BUILD_ENV] = "1"
    environment[CAPTURE_BACKEND_ENV] = args.backend
    try:
        adapter = create_platform_adapter(environ=environment)
        backend = adapter.create_screen_capture()
        result = soak_backend(
            backend,
            PsutilProcessSampler(),
            mode=args.backend,
            duration_seconds=args.duration_seconds,
            sample_interval=args.sample_interval,
            report_interval=args.report_interval,
            max_stall_seconds=args.max_stall_seconds,
            max_memory_growth_mib=args.max_memory_growth_mib,
            max_resource_growth=args.max_resource_growth,
            progress=(
                (lambda payload: write_json(args.progress_file, payload))
                if args.progress_file is not None
                else _print_progress
            ),
        )
    except (CaptureError, RuntimeError, ValueError) as error:
        result = {
            "ok": False,
            "mode": args.backend,
            "platform": platform.system(),
            "error": "setup_failed",
            "error_type": type(error).__name__,
            "privacy": {
                "frames_saved": False,
                "frames_uploaded": False,
                "pixel_data_reported": False,
            },
        }

    if args.result_file is not None:
        write_json(args.result_file, result)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("error") == "permission_denied":
        return EXIT_PERMISSION_DENIED
    if result.get("error") == "interrupted":
        return EXIT_INTERRUPTED
    return 0 if result.get("ok") is True else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
