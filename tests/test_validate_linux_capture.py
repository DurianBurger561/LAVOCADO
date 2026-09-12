"""Tests for the privacy-safe Linux capture validation tool."""

import io
import json
import unittest
from contextlib import redirect_stdout

import numpy as np

from app.platforms.capture import (
    CaptureBackendStatus,
    CaptureFrame,
    MonitorInfo,
    detect_linux_session,
)
from scripts.validate_linux_capture import (
    main,
    route_self_check,
    validate_live_capture,
)


class FakeCapture:
    name = "fake"

    def __init__(self, sequences: list[int]) -> None:
        self.sequences = iter(sequences)
        self.started = False
        self.stop_calls = 0

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False
        self.stop_calls += 1

    def monitors(self) -> list[MonitorInfo]:
        return [MonitorInfo("private-id", 1, 0, 0, 2, 1, is_primary=True)]

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame:
        return CaptureFrame(
            image=np.zeros((1, 2, 3), dtype=np.uint8),
            monitor_id=monitor_id,
            timestamp_ns=10,
            sequence=next(self.sequences),
            changed_regions=None,
            backend="linux_xshm",
        )

    def status(self) -> CaptureBackendStatus:
        return CaptureBackendStatus(
            preferred_backend="linux_xshm",
            active_backend="linux_xshm" if self.started else None,
            fallback=False,
            fallback_reason=None,
            healthy=self.started,
            session="x11" if self.started else None,
            monitor_count=1 if self.started else 0,
            frame_age_ms=0.1 if self.started else None,
        )


class LinuxCaptureValidationTests(unittest.TestCase):
    def test_route_self_check_covers_every_linux_path(self) -> None:
        result = route_self_check()

        self.assertTrue(result["ok"])
        self.assertEqual(
            {case["case"] for case in result["cases"]},
            {"wayland", "x11", "wslg", "headless"},
        )

    def test_live_validation_checks_fresh_frames_without_pixel_output(self) -> None:
        backend = FakeCapture([1, 2])
        session = detect_linux_session(
            {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
            "generic-linux",
        )

        result = validate_live_capture(backend, session, frames=2)

        self.assertTrue(result["ok"])
        self.assertEqual(result["capture"]["active_backend"], "linux_xshm")
        self.assertEqual(
            [sample["sequence"] for sample in result["samples"]],
            [1, 2],
        )
        self.assertNotIn("private-id", json.dumps(result))
        self.assertNotIn("image", json.dumps(result))
        self.assertEqual(
            result["privacy"],
            {"frames_saved": False, "frames_uploaded": False},
        )
        self.assertEqual(backend.stop_calls, 1)

    def test_stale_sequence_fails_validation_and_still_stops_backend(self) -> None:
        backend = FakeCapture([1, 1, 1])
        session = detect_linux_session({"DISPLAY": ":0"}, "generic-linux")
        ticks = iter((0.0, 0.0, 1.0))

        with self.assertRaisesRegex(RuntimeError, "stopped advancing"):
            validate_live_capture(
                backend,
                session,
                frames=2,
                fresh_frame_timeout=0.5,
                clock=lambda: next(ticks),
                sleeper=lambda _seconds: None,
            )

        self.assertEqual(backend.stop_calls, 1)

    def test_self_check_cli_prints_json_and_never_starts_capture(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            exit_code = main(["--self-check"])

        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(output.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
