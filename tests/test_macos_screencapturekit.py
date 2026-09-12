"""Tests for ScreenCaptureKit slots and permission-safe fallback behavior."""

import unittest

import numpy as np

from app.platforms.capture import (
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
    MonitorInfo,
    Rect,
    ScreenCaptureKitCapture,
)
from app.platforms.capture.macos_screencapturekit import (
    _check_screen_recording_permission,
    _rect_from_value,
)


class FakeBridge:
    def __init__(
        self,
        *,
        start_error: Exception | None = None,
    ) -> None:
        self.start_error = start_error
        self.frame_handler = None
        self.error_handler = None
        self.stopped = False

    def start(self, frame_handler, error_handler):
        if self.start_error is not None:
            raise self.start_error
        self.frame_handler = frame_handler
        self.error_handler = error_handler
        return [MonitorInfo("77", 1, 0, 0, 4, 2, is_primary=True)]

    def stop(self) -> None:
        self.stopped = True

    def publish(
        self,
        image: np.ndarray,
        regions: tuple[Rect, ...] | None = None,
    ) -> None:
        self.frame_handler("77", image, regions)


class PermissionAPI:
    def __init__(self, *, preflight: bool, request: bool) -> None:
        self.preflight = preflight
        self.request = request
        self.requested = False

    def CGPreflightScreenCaptureAccess(self) -> bool:
        return self.preflight

    def CGRequestScreenCaptureAccess(self) -> bool:
        self.requested = True
        return self.request


class ScreenCaptureKitCaptureTests(unittest.TestCase):
    def test_latest_slot_replaces_old_frame_without_queueing(self) -> None:
        bridge = FakeBridge()
        ticks = iter((100, 110, 120, 130))
        backend = ScreenCaptureKitCapture(
            bridge_factory=lambda: bridge,
            clock_ns=lambda: next(ticks),
            first_frame_timeout=0,
        )
        backend.start()
        first_image = np.zeros((2, 4, 3), dtype=np.uint8)
        latest_image = np.ones((2, 4, 3), dtype=np.uint8)
        regions = (Rect(1, 0, 2, 2),)

        bridge.publish(first_image)
        bridge.publish(latest_image, regions)
        frame = backend.get_latest_frame("77")
        repeated = backend.get_latest_frame("77")
        status = backend.status()

        self.assertTrue(np.array_equal(frame.image, latest_image))
        self.assertEqual(frame.sequence, 2)
        self.assertEqual(repeated.sequence, 2)
        self.assertEqual(frame.changed_regions, regions)
        self.assertEqual(frame.backend, "macos_screencapturekit")
        self.assertEqual(status.frame_age_ms, 0.00001)

    def test_missing_first_frame_is_recoverable(self) -> None:
        bridge = FakeBridge()
        backend = ScreenCaptureKitCapture(
            bridge_factory=lambda: bridge,
            first_frame_timeout=0,
        )
        backend.start()

        with self.assertRaises(CaptureRecoverableError):
            backend.get_latest_frame("77")

    def test_stream_error_is_reported_to_fallback_wrapper(self) -> None:
        bridge = FakeBridge()
        backend = ScreenCaptureKitCapture(
            bridge_factory=lambda: bridge,
            first_frame_timeout=0,
        )
        backend.start()
        bridge.error_handler(CaptureRecoverableError("stream stopped"))

        with self.assertRaises(CaptureRecoverableError):
            backend.get_latest_frame("77")
        self.assertFalse(backend.status().healthy)

    def test_unavailable_framework_is_a_fallback_candidate(self) -> None:
        bridge = FakeBridge(start_error=CaptureUnavailableError("unsupported"))
        backend = ScreenCaptureKitCapture(bridge_factory=lambda: bridge)

        with self.assertRaises(CaptureUnavailableError):
            backend.start()
        self.assertTrue(bridge.stopped)

    def test_permission_denial_is_explicit_and_cannot_be_bypassed(self) -> None:
        api = PermissionAPI(preflight=False, request=False)

        with self.assertRaises(CapturePermissionDeniedError):
            _check_screen_recording_permission(api)

        self.assertTrue(api.requested)

    def test_existing_permission_does_not_show_another_prompt(self) -> None:
        api = PermissionAPI(preflight=True, request=False)

        _check_screen_recording_permission(api)

        self.assertFalse(api.requested)

    def test_dirty_rect_metadata_is_normalized(self) -> None:
        region = _rect_from_value({"X": 1.2, "Y": 2.7, "Width": 3, "Height": 4})

        self.assertEqual(region, Rect(1, 3, 3, 4))

    def test_stop_releases_native_streams(self) -> None:
        bridge = FakeBridge()
        backend = ScreenCaptureKitCapture(bridge_factory=lambda: bridge)
        backend.start()

        backend.stop()

        self.assertTrue(bridge.stopped)
        self.assertFalse(backend.status().healthy)


if __name__ == "__main__":
    unittest.main()
