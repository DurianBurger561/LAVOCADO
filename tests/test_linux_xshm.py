"""Tests for Linux X11 MIT-SHM capture and its availability boundary."""

import unittest
from types import SimpleNamespace

from mss.exception import ScreenShotError

from app.platforms.capture import (
    CaptureFatalError,
    CaptureRecoverableError,
    CaptureUnavailableError,
    XShmAvailability,
    XShmCapture,
)
from app.platforms.capture.linux_xshm import _read_xshm_availability


class FakeScreenshot:
    size = (2, 1)
    bgra = bytes([10, 20, 30, 255, 40, 50, 60, 255])


class FakeXShm:
    def __init__(
        self,
        *,
        availability: XShmAvailability = XShmAvailability.UNKNOWN,
        next_availability: XShmAvailability = XShmAvailability.AVAILABLE,
        fail_grab: bool = False,
    ) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 4, "height": 1},
            {"left": 2, "top": 0, "width": 2, "height": 1},
            {"left": 0, "top": 0, "width": 2, "height": 1},
        ]
        self.availability = availability
        self.next_availability = next_availability
        self.fail_grab = fail_grab
        self.closed = False

    def grab(self, _monitor):
        if self.fail_grab:
            raise ScreenShotError("X connection reset")
        self.availability = self.next_availability
        return FakeScreenshot()

    def close(self) -> None:
        self.closed = True


def read_fake_availability(capture: FakeXShm) -> XShmAvailability:
    return capture.availability


class XShmCaptureTests(unittest.TestCase):
    def test_outputs_bgr_frames_after_xshm_is_confirmed(self) -> None:
        raw = FakeXShm()
        backend = XShmCapture(
            capture_factory=lambda: raw,
            availability_reader=read_fake_availability,
            clock_ns=lambda: 5_000_000,
        )
        backend.start()

        frame = backend.get_latest_frame("1")

        self.assertEqual(frame.image.tolist(), [[[10, 20, 30], [40, 50, 60]]])
        self.assertTrue(frame.image.flags.c_contiguous)
        self.assertEqual(frame.backend, "linux_xshm")
        self.assertEqual(frame.sequence, 1)
        self.assertEqual(frame.timestamp_ns, 5_000_000)
        self.assertEqual(backend.status().session, "x11")
        self.assertEqual(backend.status().monitor_count, 2)

    def test_known_unavailable_xshm_fails_start_and_releases_resources(self) -> None:
        raw = FakeXShm(availability=XShmAvailability.UNAVAILABLE)
        backend = XShmCapture(
            capture_factory=lambda: raw,
            availability_reader=read_fake_availability,
        )

        with self.assertRaises(CaptureUnavailableError):
            backend.start()

        self.assertTrue(raw.closed)
        self.assertFalse(backend.status().healthy)

    def test_silent_xgetimage_downgrade_is_a_recoverable_native_failure(self) -> None:
        raw = FakeXShm(next_availability=XShmAvailability.UNAVAILABLE)
        backend = XShmCapture(
            capture_factory=lambda: raw,
            availability_reader=read_fake_availability,
        )
        backend.start()

        with self.assertRaisesRegex(CaptureRecoverableError, "MSS fallback"):
            backend.get_latest_frame("1")

        self.assertFalse(backend.status().healthy)
        self.assertIn("MIT-SHM", backend.status().error or "")

    def test_runtime_screenshot_error_is_recoverable(self) -> None:
        raw = FakeXShm(fail_grab=True)
        backend = XShmCapture(
            capture_factory=lambda: raw,
            availability_reader=read_fake_availability,
        )
        backend.start()

        with self.assertRaises(CaptureRecoverableError):
            backend.get_latest_frame("1")

    def test_unknown_monitor_is_fatal(self) -> None:
        backend = XShmCapture(
            capture_factory=FakeXShm,
            availability_reader=read_fake_availability,
        )
        backend.start()

        with self.assertRaises(CaptureFatalError):
            backend.get_latest_frame("missing")

    def test_stop_releases_xshm_resources(self) -> None:
        raw = FakeXShm()
        backend = XShmCapture(
            capture_factory=lambda: raw,
            availability_reader=read_fake_availability,
        )
        backend.start()

        backend.stop()

        self.assertTrue(raw.closed)
        self.assertFalse(backend.status().healthy)

    def test_default_reader_maps_mss_native_state(self) -> None:
        for expected in XShmAvailability:
            capture = SimpleNamespace(
                _impl=SimpleNamespace(
                    shm_status=SimpleNamespace(name=expected.name),
                )
            )
            self.assertEqual(_read_xshm_availability(capture), expected)


if __name__ == "__main__":
    unittest.main()
