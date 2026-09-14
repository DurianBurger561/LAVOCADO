"""Tests for the privacy-safe Lab capture benchmark."""

import argparse
import json
import time
import unittest
from unittest.mock import patch

import numpy as np

from app.platforms.capture import (
    CaptureBackendStatus,
    CaptureFrame,
    CapturePermissionDeniedError,
    MonitorInfo,
)
from app.vision.violation_policy import ViolationEvidence, ViolationEvidenceType
from developer.benchmark.capture_benchmark import (
    EXIT_PERMISSION_DENIED,
    benchmark_backend,
    run_comparison,
    summarize,
)
from developer.benchmark.hardware_ipc import write_json


class FakeMemory:
    def __init__(self) -> None:
        self._values = iter((10_000_000, 11_000_000, 12_000_000, 13_000_000))

    def rss_bytes(self) -> int:
        return next(self._values)


class FakeDetector:
    def __init__(self) -> None:
        self.calls = 0

    def detect(
        self, image: np.ndarray, *, input_size: int = 640, frame_sequence: int
    ) -> list[ViolationEvidence]:
        del input_size
        self.calls += 1
        if image.shape != (2, 4, 3):
            raise AssertionError("benchmark did not preserve the full-resolution BGR frame")
        return [
            ViolationEvidence(
                ViolationEvidenceType.BREAST_EXPOSURE,
                "FEMALE_BREAST_EXPOSED", 0.8, None,
                "nudenet_640m", frame_sequence,
            )
        ] if self.calls % 2 == 0 else []


class FakeBackend:
    name = "fake-native"

    def __init__(self, start_error: Exception | None = None) -> None:
        self.start_error = start_error
        self.started = False
        self.stopped = False
        self.sequence = 0

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def stop(self) -> None:
        self.started = False
        self.stopped = True

    def monitors(self) -> list[MonitorInfo]:
        return [MonitorInfo("private-monitor-id", 1, 0, 0, 4, 2, True)]

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame:
        self.sequence += 1
        return CaptureFrame(
            image=np.zeros((2, 4, 3), dtype=np.uint8),
            monitor_id=monitor_id,
            timestamp_ns=time.monotonic_ns(),
            sequence=self.sequence,
            changed_regions=None,
            backend=self.name,
        )

    def status(self) -> CaptureBackendStatus:
        return CaptureBackendStatus(
            preferred_backend=self.name,
            active_backend=self.name if self.started else None,
            fallback=False,
            fallback_reason=None,
            healthy=self.started,
            monitor_count=1 if self.started else 0,
        )


class CaptureBenchmarkTests(unittest.TestCase):
    def test_summary_reports_median_and_p95(self) -> None:
        result = summarize([1.0, 2.0, 3.0, 4.0])

        self.assertEqual(result["median_ms"], 2.5)
        self.assertEqual(result["p95_ms"], 3.85)

    def test_benchmark_reports_only_aggregate_metadata(self) -> None:
        backend = FakeBackend()
        detector = FakeDetector()

        result = benchmark_backend(
            backend,
            detector,
            FakeMemory(),
            mode="native",
            frames=2,
            warmup=1,
            fresh_frame_timeout=0.1,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["active_backend"], "fake-native")
        self.assertEqual(result["displays"][0]["resolution"], "4x2")
        self.assertEqual(result["displays"][0]["capture_latency"]["samples"], 2)
        self.assertEqual(result["displays"][0]["candidate_count"], 1)
        self.assertEqual(detector.calls, 3)
        self.assertTrue(backend.stopped)
        serialized = json.dumps(result)
        self.assertNotIn("private-monitor-id", serialized)
        self.assertNotIn("image", serialized)

    def test_backend_is_stopped_when_start_is_denied(self) -> None:
        backend = FakeBackend(CapturePermissionDeniedError("denied"))

        with self.assertRaises(CapturePermissionDeniedError):
            benchmark_backend(
                backend,
                FakeDetector(),
                FakeMemory(),
                mode="native",
                frames=1,
                warmup=0,
                fresh_frame_timeout=0.1,
            )

        self.assertTrue(backend.stopped)

    def test_comparison_stops_before_mss_after_permission_denial(self) -> None:
        arguments = argparse.Namespace(
            frames=2,
            warmup=1,
            fresh_frame_timeout=1.0,
        )
        denied = {
            "ok": False,
            "mode": "native",
            "error": "permission_denied",
        }

        def denied_worker(command, **_kwargs):
            write_json(command[command.index("--result-file") + 1], denied)
            return type("Completed", (), {"returncode": EXIT_PERMISSION_DENIED})()

        with patch(
            "developer.benchmark.capture_benchmark.subprocess.run",
            side_effect=denied_worker,
        ) as run:
            result, exit_code = run_comparison(arguments)

        self.assertEqual(exit_code, EXIT_PERMISSION_DENIED)
        self.assertTrue(result["mss_skipped"])
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
