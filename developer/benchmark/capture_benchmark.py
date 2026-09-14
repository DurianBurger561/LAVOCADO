"""Compare capture backends without retaining or uploading screen pixels."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

import numpy as np

from app.platforms import create_platform_adapter
from app.platforms.capture import (
    CAPTURE_BACKEND_ENV,
    DEVELOPER_BUILD_ENV,
    CaptureError,
    CapturePermissionDeniedError,
    ScreenCaptureBackend,
)
from app.vision.detectors.nudenet import NudeNetPrimaryDetector
from app.vision.violation_policy import ViolationEvidence
from developer.benchmark.hardware_ipc import read_json, worker_command, write_json

EXIT_FAILED = 1
EXIT_PERMISSION_DENIED = 2


class DetectorLike(Protocol):
    """Detection seam used by the benchmark and its tests."""

    def detect(
        self, image: np.ndarray, *, input_size: int = 640, frame_sequence: int
    ) -> list[ViolationEvidence]: ...


class MemorySampler(Protocol):
    """Return the current process resident memory in bytes."""

    def rss_bytes(self) -> int: ...


class PsutilMemorySampler:
    """Cross-platform resident-memory sampler loaded only for benchmarks."""

    def __init__(self) -> None:
        try:
            import psutil
        except ImportError as error:
            raise RuntimeError(
                "Capture benchmarks require requirements-developer.txt"
            ) from error
        self._process = psutil.Process()

    def rss_bytes(self) -> int:
        return int(self._process.memory_info().rss)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot summarize an empty sample")
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(values: list[float]) -> dict[str, float | int]:
    """Return stable aggregate timing fields in milliseconds."""

    if not values:
        raise ValueError("cannot summarize an empty sample")
    return {
        "samples": len(values),
        "mean_ms": round(statistics.mean(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(_percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3),
    }


def _canonical_frame(image: np.ndarray) -> np.ndarray:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise RuntimeError("Capture returned an invalid BGR frame")
    return np.ascontiguousarray(image)


def _next_fresh_frame(
    backend: ScreenCaptureBackend,
    monitor_id: str,
    previous_sequence: int,
    *,
    timeout_seconds: float,
    clock_ns: Callable[[], int],
    sleeper: Callable[[float], None],
):
    deadline = clock_ns() + int(timeout_seconds * 1_000_000_000)
    while True:
        frame = backend.get_latest_frame(monitor_id)
        if frame is None:
            raise RuntimeError("Capture backend returned no frame")
        if frame.monitor_id != monitor_id:
            raise RuntimeError("Capture backend returned a mismatched monitor")
        if frame.timestamp_ns < 1:
            raise RuntimeError("Capture backend returned an invalid timestamp")
        if frame.sequence > previous_sequence:
            return frame
        if clock_ns() >= deadline:
            raise RuntimeError("Capture sequence stopped advancing")
        sleeper(0.005)


def benchmark_backend(
    backend: ScreenCaptureBackend,
    detector: DetectorLike,
    memory: MemorySampler,
    *,
    mode: str,
    frames: int,
    warmup: int,
    fresh_frame_timeout: float,
    clock_ns: Callable[[], int] = time.monotonic_ns,
    cpu_clock: Callable[[], float] = time.process_time,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Benchmark one backend and return only aggregate scalar metadata."""

    if frames < 1 or warmup < 0 or fresh_frame_timeout <= 0:
        raise ValueError("frames and timeout must be positive; warmup cannot be negative")

    baseline_rss = memory.rss_bytes()
    peak_rss = baseline_rss
    try:
        backend.start()
        monitors = backend.monitors()
        if not monitors:
            raise RuntimeError("Capture backend returned no physical displays")
        last_sequences = {monitor.id: 0 for monitor in monitors}

        for _ in range(warmup):
            for monitor in monitors:
                frame = _next_fresh_frame(
                    backend,
                    monitor.id,
                    last_sequences[monitor.id],
                    timeout_seconds=fresh_frame_timeout,
                    clock_ns=clock_ns,
                    sleeper=sleeper,
                )
                last_sequences[monitor.id] = frame.sequence
                detector.detect(
                    _canonical_frame(frame.image), input_size=640, frame_sequence=frame.sequence
                )
                peak_rss = max(peak_rss, memory.rss_bytes())

        samples = {
            monitor.id: {
                "monitor_index": monitor.index,
                "width": monitor.width,
                "height": monitor.height,
                "capture_latency": [],
                "frame_age": [],
                "detection_latency": [],
                "capture_to_decision": [],
                "candidate_count": 0,
            }
            for monitor in monitors
        }
        wall_started_ns = clock_ns()
        cpu_started = cpu_clock()
        for _ in range(frames):
            for monitor in monitors:
                capture_started_ns = clock_ns()
                frame = _next_fresh_frame(
                    backend,
                    monitor.id,
                    last_sequences[monitor.id],
                    timeout_seconds=fresh_frame_timeout,
                    clock_ns=clock_ns,
                    sleeper=sleeper,
                )
                captured_ns = clock_ns()
                last_sequences[monitor.id] = frame.sequence
                detection_started_ns = clock_ns()
                evidence = detector.detect(
                    _canonical_frame(frame.image), input_size=640, frame_sequence=frame.sequence
                )
                decision_finished_ns = clock_ns()

                sample = samples[monitor.id]
                sample["capture_latency"].append(
                    (captured_ns - capture_started_ns) / 1_000_000
                )
                sample["frame_age"].append(
                    max(0.0, (captured_ns - frame.timestamp_ns) / 1_000_000)
                )
                sample["detection_latency"].append(
                    (decision_finished_ns - detection_started_ns) / 1_000_000
                )
                sample["capture_to_decision"].append(
                    max(
                        0.0,
                        (decision_finished_ns - frame.timestamp_ns) / 1_000_000,
                    )
                )
                sample["candidate_count"] += int(bool(evidence))
                peak_rss = max(peak_rss, memory.rss_bytes())

        cpu_elapsed = max(0.0, cpu_clock() - cpu_started)
        wall_elapsed = max(0.0, (clock_ns() - wall_started_ns) / 1_000_000_000)
        status = backend.status()
        display_results = []
        for sample in samples.values():
            display_results.append(
                {
                    "monitor_index": sample["monitor_index"],
                    "resolution": f'{sample["width"]}x{sample["height"]}',
                    "capture_latency": summarize(sample["capture_latency"]),
                    "frame_age": summarize(sample["frame_age"]),
                    "detection_latency": summarize(sample["detection_latency"]),
                    "capture_to_decision": summarize(
                        sample["capture_to_decision"]
                    ),
                    "candidate_count": sample["candidate_count"],
                    "sequence_advanced": True,
                    "timestamp_present": True,
                }
            )

        return {
            "ok": True,
            "mode": mode,
            "platform": platform.system(),
            "preferred_backend": status.preferred_backend,
            "active_backend": status.active_backend,
            "monitor_count": len(monitors),
            "frames_per_monitor": frames,
            "detector": {
                "model_variant": str(
                    getattr(detector, "model_variant", "injected")
                ),
                "inference_resolution": getattr(
                    detector,
                    "inference_resolution",
                    None,
                ),
            },
            "displays": display_results,
            "process": {
                "wall_seconds": round(wall_elapsed, 3),
                "cpu_percent": round(
                    0.0 if wall_elapsed == 0 else cpu_elapsed / wall_elapsed * 100,
                    2,
                ),
                "rss_baseline_mib": round(baseline_rss / 1_048_576, 2),
                "rss_peak_mib": round(peak_rss / 1_048_576, 2),
                "rss_delta_mib": round(
                    max(0, peak_rss - baseline_rss) / 1_048_576,
                    2,
                ),
            },
            "privacy": {
                "frames_saved": False,
                "frames_uploaded": False,
                "pixel_data_reported": False,
            },
        }
    finally:
        backend.stop()


def _error_result(mode: str, category: str, error: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "mode": mode,
        "platform": platform.system(),
        "error": category,
        "error_type": type(error).__name__,
        "privacy": {
            "frames_saved": False,
            "frames_uploaded": False,
            "pixel_data_reported": False,
        },
    }


def run_single(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    environment = dict(os.environ)
    environment[DEVELOPER_BUILD_ENV] = "1"
    environment[CAPTURE_BACKEND_ENV] = args.backend
    try:
        adapter = create_platform_adapter(environ=environment)
        backend = adapter.create_screen_capture()
        memory = PsutilMemorySampler()
        result = benchmark_backend(
            backend,
            NudeNetPrimaryDetector(),
            memory,
            mode=args.backend,
            frames=args.frames,
            warmup=args.warmup,
            fresh_frame_timeout=args.fresh_frame_timeout,
        )
    except CapturePermissionDeniedError as error:
        return _error_result(args.backend, "permission_denied", error), EXIT_PERMISSION_DENIED
    except (CaptureError, RuntimeError, ValueError) as error:
        return _error_result(args.backend, "benchmark_failed", error), EXIT_FAILED
    return result, 0


def _child_command(args: argparse.Namespace, mode: str, result_file: Path) -> list[str]:
    return worker_command(
        "capture",
        "--backend",
        mode,
        "--frames",
        str(args.frames),
        "--warmup",
        str(args.warmup),
        "--fresh-frame-timeout",
        str(args.fresh_frame_timeout),
        "--child",
        "--result-file",
        str(result_file),
    )


def run_comparison(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    results: list[dict[str, Any]] = []
    exit_code = 0
    with TemporaryDirectory(prefix="lavocado-capture-") as temporary:
        for mode in ("native", "mss"):
            if getattr(args, "progress_file", None) is not None:
                write_json(args.progress_file, {"backend": mode, "completed": len(results), "total": 2})
            result_file = Path(temporary) / f"{mode}.json"
            completed = subprocess.run(
                _child_command(args, mode, result_file),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            result = read_json(result_file)
            if result is None:
                result = _error_result(
                    mode,
                    "benchmark_process_failed",
                    RuntimeError("Benchmark child returned invalid output"),
                )
            results.append(result)
            if completed.returncode == EXIT_PERMISSION_DENIED:
                return {
                    "ok": False,
                    "comparison": results,
                    "mss_skipped": True,
                    "reason": "permission_denied",
                }, EXIT_PERMISSION_DENIED
            if completed.returncode != 0:
                exit_code = EXIT_FAILED

    return {
        "ok": all(result.get("ok") is True for result in results),
        "comparison": results,
        "isolated_processes": True,
    }, exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("auto", "native", "mss", "both"),
        default="both",
        help="backend mode to benchmark (default: both)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=30,
        help="measured fresh frames per display (default: 30)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="unmeasured warmup frames per display (default: 3)",
    )
    parser.add_argument(
        "--fresh-frame-timeout",
        type=float,
        default=5.0,
        help="seconds to wait for an advancing frame sequence (default: 5)",
    )
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--result-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--progress-file", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.frames < 1 or args.warmup < 0 or args.fresh_frame_timeout <= 0:
        result = _error_result(
            args.backend, "invalid_arguments", ValueError("invalid benchmark arguments")
        )
        _emit(args, result)
        return EXIT_FAILED

    if args.backend == "both" and not args.child:
        result, exit_code = run_comparison(args)
    else:
        if args.backend == "both":
            result = _error_result(
                args.backend,
                "invalid_arguments",
                ValueError("child mode requires one backend"),
            )
            exit_code = EXIT_FAILED
        else:
            result, exit_code = run_single(args)
    _emit(args, result)
    return exit_code


def _emit(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if args.result_file is not None:
        write_json(args.result_file, result)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
