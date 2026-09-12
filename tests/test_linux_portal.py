"""Tests for permission-safe Wayland Portal and PipeWire capture."""

import unittest
from types import SimpleNamespace

import numpy as np

from app.platforms.capture import (
    CaptureBackendStatus,
    CaptureFatalError,
    CaptureFrame,
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
    FallbackCaptureBackend,
    MonitorInfo,
    PipeWirePortalCapture,
)
from app.platforms.capture.linux_portal import (
    _PortalPipeWireBridge,
    _gstreamer_command,
    _portal_dbus_error,
    _portal_response_error,
    _streams_from_response,
)


class FakePortalBridge:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.frame_handler = None
        self.error_handler = None
        self.stopped = False

    def start(self, frame_handler, error_handler):
        if self.error is not None:
            raise self.error
        self.frame_handler = frame_handler
        self.error_handler = error_handler
        return [MonitorInfo("display-a", 1, 0, 0, 2, 1, is_primary=True)]

    def stop(self) -> None:
        self.stopped = True

    def publish(self, image: np.ndarray) -> None:
        self.frame_handler("display-a", image)

    def fail(self, error: CaptureRecoverableError) -> None:
        self.error_handler(error)


class StubFallback:
    name = "mss"

    def __init__(self) -> None:
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        return None

    def monitors(self) -> list[MonitorInfo]:
        return []

    def get_latest_frame(self, _monitor_id: str) -> CaptureFrame | None:
        return None

    def status(self) -> CaptureBackendStatus:
        return CaptureBackendStatus("mss", "mss", False, None, True)


class PipeWirePortalCaptureTests(unittest.TestCase):
    def test_latest_slot_replaces_frames_without_queueing(self) -> None:
        bridge = FakePortalBridge()
        timestamps = iter((100, 200, 300, 400))
        backend = PipeWirePortalCapture(
            bridge_factory=lambda: bridge,
            clock_ns=lambda: next(timestamps),
        )
        backend.start()
        bridge.publish(np.zeros((1, 2, 3), dtype=np.uint8))
        bridge.publish(np.full((1, 2, 3), 9, dtype=np.uint8))

        frame = backend.get_latest_frame("display-a")

        self.assertEqual(frame.image.tolist(), [[[9, 9, 9], [9, 9, 9]]])
        self.assertEqual(frame.sequence, 2)
        self.assertEqual(frame.backend, "linux_pipewire_portal")
        self.assertEqual(backend.status().session, "wayland-portal")

    def test_user_cancellation_never_activates_mss(self) -> None:
        bridge = FakePortalBridge(
            CapturePermissionDeniedError("user cancelled Portal dialog")
        )
        fallback = StubFallback()
        backend = FallbackCaptureBackend(
            PipeWirePortalCapture(bridge_factory=lambda: bridge),
            fallback,
        )

        with self.assertRaises(CapturePermissionDeniedError):
            backend.start()

        self.assertEqual(fallback.start_calls, 0)
        self.assertTrue(bridge.stopped)

    def test_technical_unavailability_is_available_to_fallback_policy(self) -> None:
        bridge = FakePortalBridge(CaptureUnavailableError("portal missing"))
        backend = PipeWirePortalCapture(bridge_factory=lambda: bridge)

        with self.assertRaises(CaptureUnavailableError):
            backend.start()

        self.assertTrue(bridge.stopped)

    def test_runtime_stream_failure_is_reported(self) -> None:
        bridge = FakePortalBridge()
        backend = PipeWirePortalCapture(bridge_factory=lambda: bridge)
        backend.start()
        bridge.fail(CaptureRecoverableError("PipeWire disconnected"))

        with self.assertRaisesRegex(CaptureRecoverableError, "disconnected"):
            backend.get_latest_frame("display-a")

        self.assertFalse(backend.status().healthy)

    def test_missing_first_frame_is_recoverable(self) -> None:
        backend = PipeWirePortalCapture(
            bridge_factory=FakePortalBridge,
            first_frame_timeout=0,
        )
        backend.start()

        with self.assertRaises(CaptureRecoverableError):
            backend.get_latest_frame("display-a")

    def test_unknown_monitor_is_fatal(self) -> None:
        backend = PipeWirePortalCapture(bridge_factory=FakePortalBridge)
        backend.start()

        with self.assertRaises(CaptureFatalError):
            backend.get_latest_frame("missing")

    def test_stop_releases_portal_session(self) -> None:
        bridge = FakePortalBridge()
        backend = PipeWirePortalCapture(bridge_factory=lambda: bridge)
        backend.start()

        backend.stop()

        self.assertTrue(bridge.stopped)
        self.assertFalse(backend.status().healthy)


class PortalProtocolTests(unittest.TestCase):
    def test_only_explicit_portal_cancellation_is_permission_denied(self) -> None:
        self.assertIsNone(_portal_response_error("Start", 0))
        self.assertIsInstance(
            _portal_response_error("Start", 1),
            CapturePermissionDeniedError,
        )
        self.assertIsInstance(
            _portal_response_error("Start", 2),
            CaptureUnavailableError,
        )

    def test_dbus_access_denial_cannot_be_hidden_by_mss(self) -> None:
        self.assertIsInstance(
            _portal_dbus_error(
                "Start",
                "org.freedesktop.portal.Error.NotAllowed",
                "Screen cast is disabled",
            ),
            CapturePermissionDeniedError,
        )
        self.assertIsInstance(
            _portal_dbus_error(
                "Start",
                "org.freedesktop.DBus.Error.ServiceUnknown",
                "Portal service is missing",
            ),
            CaptureUnavailableError,
        )

    def test_portal_streams_become_monitor_metadata(self) -> None:
        variant = lambda value: SimpleNamespace(value=value)
        streams = _streams_from_response(
            {
                "streams": variant(
                    [
                        [
                            42,
                            {
                                "id": variant("display-a"),
                                "position": variant([1920, 0]),
                                "size": variant([2560, 1440]),
                            },
                        ]
                    ]
                )
            }
        )

        self.assertEqual(streams[0].monitor_id, "display-a")
        self.assertEqual(streams[0].node_id, 42)
        self.assertEqual(
            (streams[0].left, streams[0].top),
            (1920, 0),
        )
        self.assertEqual(
            (streams[0].width, streams[0].height),
            (2560, 1440),
        )

    def test_gstreamer_pipeline_targets_portal_fd_and_bgr_frames(self) -> None:
        stream = _streams_from_response(
            {
                "streams": [
                    [
                        42,
                        {
                            "id": "display-a",
                            "position": [0, 0],
                            "size": [1920, 1080],
                        },
                    ]
                ]
            }
        )[0]

        command = _gstreamer_command("/usr/bin/gst-launch-1.0", 7, stream, 5)

        self.assertIn("fd=7", command)
        self.assertIn("path=42", command)
        self.assertIn("format=BGRx", " ".join(command))
        self.assertIn("framerate=5/1", " ".join(command))

    def test_missing_gstreamer_is_technical_unavailability(self) -> None:
        bridge = _PortalPipeWireBridge(executable_finder=lambda _name: None)

        with self.assertRaises(CaptureUnavailableError):
            bridge.start(lambda *_args: None, lambda _error: None)

    def test_missing_pipewire_plugin_is_technical_unavailability(self) -> None:
        bridge = _PortalPipeWireBridge(
            executable_finder=lambda name: f"/usr/bin/{name}",
            command_runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
        )

        with self.assertRaisesRegex(CaptureUnavailableError, "pipewiresrc"):
            bridge.start(lambda *_args: None, lambda _error: None)


if __name__ == "__main__":
    unittest.main()
