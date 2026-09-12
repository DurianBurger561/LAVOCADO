"""Tests for MSS normalization and native-to-MSS fallback policy."""

import unittest

import numpy as np
from mss.exception import ScreenShotError

from app.platforms.capture import (
    CaptureBackendStatus,
    CaptureFrame,
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
    FallbackCaptureBackend,
    MonitorInfo,
    MSSCapture,
)


class FakeScreenshot:
    size = (2, 1)
    bgra = bytes([10, 20, 30, 255, 40, 50, 60, 255])


class FakeMSS:
    def __init__(self, *, fail_grab: bool = False) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 4, "height": 1},
            {"left": 2, "top": 0, "width": 2, "height": 1},
            {"left": 0, "top": 0, "width": 2, "height": 1},
        ]
        self.fail_grab = fail_grab
        self.closed = False

    def grab(self, _monitor):
        if self.fail_grab:
            raise ScreenShotError("temporary failure")
        return FakeScreenshot()

    def close(self) -> None:
        self.closed = True


def frame(backend: str = "native", sequence: int = 1) -> CaptureFrame:
    return CaptureFrame(
        image=np.zeros((1, 2, 3), dtype=np.uint8),
        monitor_id="1",
        timestamp_ns=100,
        sequence=sequence,
        changed_regions=None,
        backend=backend,
    )


class StubBackend:
    def __init__(
        self,
        name: str,
        *,
        start_effects: list[Exception | None] | None = None,
        frame_effects: list[Exception | CaptureFrame] | None = None,
    ) -> None:
        self.name = name
        self.start_effects = list(start_effects or [])
        self.frame_effects = list(frame_effects or [frame(name)])
        self.start_calls = 0
        self.stop_calls = 0
        self.started = False

    def start(self) -> None:
        self.start_calls += 1
        if self.start_effects:
            effect = self.start_effects.pop(0)
            if effect is not None:
                raise effect
        self.started = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.started = False

    def monitors(self) -> list[MonitorInfo]:
        return [MonitorInfo("1", 1, 0, 0, 2, 1, is_primary=True)]

    def get_latest_frame(self, _monitor_id: str) -> CaptureFrame:
        effect = self.frame_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect

    def status(self) -> CaptureBackendStatus:
        return CaptureBackendStatus(
            preferred_backend=self.name,
            active_backend=self.name if self.started else None,
            fallback=False,
            fallback_reason=None,
            healthy=self.started,
            monitor_count=1 if self.started else 0,
        )


class MSSCaptureTests(unittest.TestCase):
    def test_outputs_normalized_bgr_frame_and_fresh_sequence(self) -> None:
        raw = FakeMSS()
        ticks = iter((123, 123, 5_000_123))
        backend = MSSCapture(
            capture_factory=lambda: raw,
            clock_ns=lambda: next(ticks),
        )
        backend.start()

        first = backend.get_latest_frame("1")
        second = backend.get_latest_frame("1")

        self.assertEqual(backend.monitors()[1].is_primary, True)
        self.assertEqual(first.image.tolist(), [[[10, 20, 30], [40, 50, 60]]])
        self.assertEqual(first.image.dtype, np.uint8)
        self.assertTrue(first.image.flags.c_contiguous)
        self.assertEqual(first.timestamp_ns, 123)
        self.assertEqual((first.sequence, second.sequence), (1, 2))
        self.assertIsNone(first.changed_regions)
        self.assertEqual(first.backend, "mss")
        self.assertEqual(backend.status().frame_age_ms, 5.0)

    def test_runtime_screen_error_is_recoverable(self) -> None:
        backend = MSSCapture(capture_factory=lambda: FakeMSS(fail_grab=True))
        backend.start()

        with self.assertRaises(CaptureRecoverableError):
            backend.get_latest_frame("1")

    def test_stop_releases_mss(self) -> None:
        raw = FakeMSS()
        backend = MSSCapture(capture_factory=lambda: raw)
        backend.start()

        backend.stop()

        self.assertTrue(raw.closed)
        self.assertFalse(backend.status().healthy)


class FallbackCaptureTests(unittest.TestCase):
    def test_primary_success_remains_active(self) -> None:
        primary = StubBackend("native")
        fallback = StubBackend("mss")
        backend = FallbackCaptureBackend(primary, fallback)

        backend.start()

        self.assertEqual(backend.status().active_backend, "native")
        self.assertFalse(backend.status().fallback)
        self.assertEqual(fallback.start_calls, 0)

    def test_unavailable_primary_starts_mss(self) -> None:
        primary = StubBackend(
            "native",
            start_effects=[CaptureUnavailableError("not supported")],
        )
        fallback = StubBackend("mss")
        backend = FallbackCaptureBackend(primary, fallback)

        backend.start()

        status = backend.status()
        self.assertEqual(status.preferred_backend, "native")
        self.assertEqual(status.active_backend, "mss")
        self.assertTrue(status.fallback)
        self.assertIn("not supported", status.fallback_reason or "")

    def test_recoverable_runtime_failure_switches_after_retry(self) -> None:
        primary = StubBackend(
            "native",
            frame_effects=[
                CaptureRecoverableError("access lost"),
                CaptureRecoverableError("still lost"),
            ],
        )
        fallback = StubBackend("mss", frame_effects=[frame("mss")])
        backend = FallbackCaptureBackend(primary, fallback, recovery_attempts=1)
        backend.start()

        captured = backend.get_latest_frame("1")

        self.assertEqual(captured.backend, "mss")
        self.assertEqual(primary.start_calls, 2)
        self.assertEqual(fallback.start_calls, 1)
        self.assertTrue(backend.status().fallback)

    def test_recoverable_runtime_failure_can_reinitialize_primary(self) -> None:
        primary = StubBackend(
            "native",
            frame_effects=[
                CaptureRecoverableError("access lost"),
                frame("native", sequence=2),
            ],
        )
        fallback = StubBackend("mss")
        backend = FallbackCaptureBackend(primary, fallback, recovery_attempts=1)
        backend.start()

        captured = backend.get_latest_frame("1")

        self.assertEqual(captured.sequence, 2)
        self.assertEqual(fallback.start_calls, 0)
        self.assertFalse(backend.status().fallback)

    def test_permission_denied_never_starts_fallback(self) -> None:
        primary = StubBackend(
            "native",
            start_effects=[CapturePermissionDeniedError("user denied")],
        )
        fallback = StubBackend("mss")
        backend = FallbackCaptureBackend(primary, fallback)

        with self.assertRaises(CapturePermissionDeniedError):
            backend.start()

        self.assertEqual(fallback.start_calls, 0)
        self.assertIsNone(backend.status().active_backend)


if __name__ == "__main__":
    unittest.main()
