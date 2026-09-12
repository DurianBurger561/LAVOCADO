"""Tests for the Windows DXGI capture adapter without requiring Windows."""

import unittest

import numpy as np

from app.platforms.capture import (
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
    MonitorInfo,
    WindowsDXGICapture,
)


class FakeCamera:
    def __init__(self, frame: np.ndarray | None = None, error: Exception | None = None):
        self.frame = np.zeros((2, 3, 3), dtype=np.uint8) if frame is None else frame
        self.error = error
        self.started_with = None
        self.stopped = False
        self.released = False

    def start(self, **kwargs) -> None:
        if self.error is not None:
            raise self.error
        self.started_with = kwargs

    def grab(self, **_kwargs):
        if self.error is not None:
            raise self.error
        return self.frame

    def stop(self) -> None:
        self.stopped = True

    def release(self) -> None:
        self.released = True


class FakeDXCam:
    def __init__(self, cameras: list[FakeCamera]) -> None:
        self.cameras = cameras
        self.create_calls: list[dict[str, object]] = []

    @staticmethod
    def output_info() -> str:
        return (
            "Device[0] Output[0]: Res:(3, 2) Rot:0 Primary:True\n"
            "Device[0] Output[1]: Res:(4, 2) Rot:0 Primary:False\n"
        )

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return self.cameras[len(self.create_calls) - 1]


def monitors() -> list[MonitorInfo]:
    return [
        MonitorInfo("1", 1, 0, 0, 3, 2, is_primary=True),
        MonitorInfo("2", 2, 3, 0, 4, 2, is_primary=False),
    ]


class WindowsDXGICaptureTests(unittest.TestCase):
    def test_captures_each_dxgi_output_as_normalized_bgr(self) -> None:
        cameras = [FakeCamera(), FakeCamera(np.ones((2, 4, 3), dtype=np.uint8))]
        module = FakeDXCam(cameras)
        ticks = iter((100, 110, 120))
        backend = WindowsDXGICapture(
            module_loader=lambda _name: module,
            monitor_provider=monitors,
            clock_ns=lambda: next(ticks),
        )

        backend.start()
        frame = backend.get_latest_frame("2")
        status = backend.status()

        self.assertEqual([item.id for item in backend.monitors()], ["1", "2"])
        self.assertEqual(frame.image.shape, (2, 4, 3))
        self.assertEqual(frame.sequence, 1)
        self.assertEqual(frame.timestamp_ns, 100)
        self.assertEqual(frame.backend, "windows_dxgi")
        self.assertIsNone(frame.changed_regions)
        self.assertEqual(module.create_calls[1]["output_idx"], 1)
        self.assertEqual(module.create_calls[1]["backend"], "dxgi")
        self.assertEqual(cameras[1].started_with["target_fps"], 30)
        self.assertTrue(status.healthy)
        self.assertEqual(status.monitor_count, 2)
        self.assertEqual(status.frame_age_ms, 0.00001)

    def test_missing_dxcam_is_unavailable_for_mss_fallback(self) -> None:
        def missing(_name: str):
            raise ImportError("not installed")

        backend = WindowsDXGICapture(module_loader=missing, monitor_provider=monitors)

        with self.assertRaises(CaptureUnavailableError):
            backend.start()

    def test_access_denied_is_not_hidden_by_fallback_policy(self) -> None:
        module = FakeDXCam([FakeCamera(error=PermissionError("Access denied"))])
        backend = WindowsDXGICapture(
            module_loader=lambda _name: module,
            monitor_provider=lambda: monitors()[:1],
        )

        with self.assertRaises(CapturePermissionDeniedError):
            backend.start()

    def test_runtime_access_lost_is_recoverable(self) -> None:
        camera = FakeCamera()
        module = FakeDXCam([camera, FakeCamera()])
        backend = WindowsDXGICapture(
            module_loader=lambda _name: module,
            monitor_provider=monitors,
        )
        backend.start()
        camera.error = RuntimeError("DXGI_ERROR_ACCESS_LOST")

        with self.assertRaises(CaptureRecoverableError):
            backend.get_latest_frame("1")

    def test_stop_releases_all_native_resources(self) -> None:
        cameras = [FakeCamera(), FakeCamera()]
        backend = WindowsDXGICapture(
            module_loader=lambda _name: FakeDXCam(cameras),
            monitor_provider=monitors,
        )
        backend.start()

        backend.stop()

        self.assertTrue(all(camera.stopped for camera in cameras))
        self.assertTrue(all(camera.released for camera in cameras))
        self.assertFalse(backend.status().healthy)


if __name__ == "__main__":
    unittest.main()
