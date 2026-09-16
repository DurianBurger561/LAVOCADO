"""Tests for adapting normalized capture frames to vision inputs."""

import unittest

import numpy as np

from app.platforms.capture import (
    CaptureBackendStatus,
    CaptureFrame,
    MonitorInfo,
)
from app.vision.capture import Capturer


class FakeBackend:
    name = "fake-native"

    def __init__(self) -> None:
        self.started = False
        self.sequence = 0
        self.monitor_list = [
            MonitorInfo("display-a", 1, 0, 0, 8, 4, is_primary=True),
            MonitorInfo("display-b", 2, 8, 0, 8, 4),
        ]

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def monitors(self) -> list[MonitorInfo]:
        return list(self.monitor_list)

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame:
        self.sequence += 1
        return CaptureFrame(
            image=np.full((4, 8, 3), (10, 20, 30), dtype=np.uint8),
            monitor_id=monitor_id,
            timestamp_ns=123,
            sequence=self.sequence,
            changed_regions=None,
            backend=self.name,
        )

    def status(self) -> CaptureBackendStatus:
        return CaptureBackendStatus(
            preferred_backend=self.name,
            active_backend=self.name,
            fallback=False,
            fallback_reason=None,
            healthy=self.started,
            monitor_count=2,
        )


class FakePlatform:
    def __init__(self, backend: FakeBackend) -> None:
        self.backend = backend

    def create_screen_capture(self) -> FakeBackend:
        return self.backend


class CaptureTests(unittest.TestCase):
    def test_returns_full_resolution_canonical_frame(self) -> None:
        backend = FakeBackend()
        capturer = Capturer(FakePlatform(backend))
        captured = capturer.grab(1)

        self.assertEqual(captured.image.shape, (4, 8, 3))
        self.assertEqual(captured.image.dtype, np.uint8)
        self.assertTrue(captured.image.flags.c_contiguous)
        self.assertEqual(captured.monitor_id, "display-a")
        self.assertEqual(captured.sequence, 1)
        self.assertEqual(captured.backend, "fake-native")
        self.assertFalse(hasattr(captured, "model_frame"))
        self.assertFalse(hasattr(captured, "original_frame"))

    def test_maps_points_using_backend_monitor_metadata(self) -> None:
        capturer = Capturer(FakePlatform(FakeBackend()))

        self.assertEqual(capturer.monitor_indexes, (1, 2))
        self.assertEqual(capturer.monitor_index_at(10, 2), 2)
        self.assertIsNone(capturer.monitor_index_at(20, 2))
        self.assertEqual(capturer.monitor_for_index(2), FakeBackend().monitor_list[1])
        self.assertEqual(capturer.monitor_for_index().id, "display-a")

    def test_close_stops_backend(self) -> None:
        backend = FakeBackend()
        capturer = Capturer(FakePlatform(backend))

        capturer.close()

        self.assertFalse(backend.started)

    def test_overlay_target_uses_latest_capture_topology(self) -> None:
        backend = FakeBackend()
        capturer = Capturer(FakePlatform(backend))
        backend.monitor_list[1] = MonitorInfo(
            "display-b", 2, -8, 4, 8, 4
        )

        self.assertEqual(capturer.monitor_for_index(2), backend.monitor_list[1])


if __name__ == "__main__":
    unittest.main()
