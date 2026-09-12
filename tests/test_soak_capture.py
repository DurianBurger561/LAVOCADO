"""Tests for long-run capture stability monitoring."""

import json
import time
import unittest

import numpy as np

from app.platforms.capture import (
    CaptureBackendStatus,
    CaptureFrame,
    CapturePermissionDeniedError,
    MonitorInfo,
)
from scripts.soak_capture import ProcessSnapshot, soak_backend


class FakeProcess:
    def __init__(self, *, leaking: bool = False) -> None:
        self.calls = 0
        self.leaking = leaking

    def snapshot(self) -> ProcessSnapshot:
        self.calls += 1
        growth = self.calls * 2_000_000 if self.leaking else 0
        return ProcessSnapshot(
            rss_bytes=100_000_000 + growth,
            thread_count=4,
            resource_count=8,
            resource_kind="file_descriptors",
        )


class FakeBackend:
    name = "fake-native"

    def __init__(
        self,
        *,
        stale: bool = False,
        start_error: Exception | None = None,
    ) -> None:
        self.stale = stale
        self.start_error = start_error
        self.started = False
        self.stop_calls = 0
        self.sequence = 0

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def stop(self) -> None:
        self.started = False
        self.stop_calls += 1

    def monitors(self) -> list[MonitorInfo]:
        return [MonitorInfo("private-id", 1, 0, 0, 4, 2, True)]

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame:
        if not self.stale or self.sequence == 0:
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
        fallback = self.started and self.sequence >= 2
        return CaptureBackendStatus(
            preferred_backend=self.name,
            active_backend=("mss" if fallback else self.name) if self.started else None,
            fallback=fallback,
            fallback_reason="recoverable failure" if fallback else None,
            healthy=self.started,
            monitor_count=1 if self.started else 0,
        )


def run_fake(
    backend: FakeBackend,
    process: FakeProcess | None = None,
    **overrides,
):
    options = {
        "mode": "auto",
        "duration_seconds": 60.0,
        "sample_interval": 0.0,
        "report_interval": 60.0,
        "max_stall_seconds": 0.001,
        "max_memory_growth_mib": 256.0,
        "max_resource_growth": 32,
        "release_grace_seconds": 0.0,
        "sleeper": lambda _seconds: None,
        "max_cycles": 3,
    }
    options.update(overrides)
    return soak_backend(backend, process or FakeProcess(), **options)


class CaptureSoakTests(unittest.TestCase):
    def test_tracks_frames_fallback_resources_and_release(self) -> None:
        backend = FakeBackend()

        result = run_fake(backend)

        self.assertTrue(result["ok"])
        self.assertEqual(result["cycles"], 3)
        self.assertEqual(result["frames"], 3)
        self.assertEqual(result["backend_transitions"][0]["to_backend"], "mss")
        self.assertTrue(result["release"]["backend_released"])
        self.assertEqual(backend.stop_calls, 1)
        serialized = json.dumps(result)
        self.assertNotIn("private-id", serialized)
        self.assertNotIn("image", serialized)

    def test_stalled_sequence_fails_the_test_and_releases_backend(self) -> None:
        backend = FakeBackend(stale=True)

        result = run_fake(backend)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "capture_failed")
        self.assertEqual(result["error_type"], "RuntimeError")
        self.assertEqual(result["cycles"], 1)
        self.assertEqual(backend.stop_calls, 1)

    def test_permission_denial_never_becomes_a_fallback_result(self) -> None:
        backend = FakeBackend(
            start_error=CapturePermissionDeniedError("denied")
        )

        result = run_fake(backend)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "permission_denied")
        self.assertEqual(result["frames"], 0)
        self.assertEqual(result["backend_transitions"], [])
        self.assertEqual(backend.stop_calls, 1)

    def test_post_stop_memory_growth_can_fail_the_soak(self) -> None:
        result = run_fake(
            FakeBackend(),
            FakeProcess(leaking=True),
            max_memory_growth_mib=1.0,
        )

        self.assertFalse(result["ok"])
        self.assertIn("memory_growth", result["threshold_failures"])
        self.assertEqual(result["error"], "stability_threshold_exceeded")


if __name__ == "__main__":
    unittest.main()
