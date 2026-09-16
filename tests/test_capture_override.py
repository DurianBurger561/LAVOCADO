"""Tests for the developer-only capture backend override."""

import sys
import unittest
from unittest.mock import patch

from app.platforms.capture import (
    CaptureBackendMode,
    FallbackCaptureBackend,
    MSSCapture,
    ScreenCaptureKitCapture,
    WindowsDXGICapture,
    create_macos_capture,
    create_windows_capture,
    resolve_capture_backend_mode,
)
from app.platforms.macos import MacOSPlatform
from app.platforms.windows import WindowsPlatform


class CaptureOverrideTests(unittest.TestCase):
    def test_user_run_ignores_backend_override(self) -> None:
        mode = resolve_capture_backend_mode(
            {"LAVOCADO_CAPTURE_BACKEND": "mss"}
        )

        self.assertIs(mode, CaptureBackendMode.AUTO)

    def test_developer_run_accepts_all_modes_case_insensitively(self) -> None:
        for value, expected in (
            ("AUTO", CaptureBackendMode.AUTO),
            ("Native", CaptureBackendMode.NATIVE),
            ("mss", CaptureBackendMode.MSS),
        ):
            with self.subTest(value=value):
                self.assertIs(
                    resolve_capture_backend_mode(
                        {
                            "LAVOCADO_DEVELOPER_BUILD": "true",
                            "LAVOCADO_CAPTURE_BACKEND": value,
                        }
                    ),
                    expected,
                )

    def test_packaged_user_build_cannot_enable_override(self) -> None:
        with patch.object(sys, "frozen", True, create=True):
            mode = resolve_capture_backend_mode(
                {
                    "LAVOCADO_DEVELOPER_BUILD": "1",
                    "LAVOCADO_CAPTURE_BACKEND": "mss",
                }
            )

        self.assertIs(mode, CaptureBackendMode.AUTO)

    def test_invalid_developer_override_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "auto, native, mss"):
            resolve_capture_backend_mode(
                {
                    "LAVOCADO_DEVELOPER_BUILD": "1",
                    "LAVOCADO_CAPTURE_BACKEND": "unknown",
                }
            )

    def test_platform_adapters_forward_the_developer_override(self) -> None:
        environment = {
            "LAVOCADO_DEVELOPER_BUILD": "1",
            "LAVOCADO_CAPTURE_BACKEND": "mss",
        }
        platforms = (
            WindowsPlatform(environ=dict(environment)),
            MacOSPlatform(environ=dict(environment)),
        )

        for platform in platforms:
            with self.subTest(platform=platform.name):
                self.assertIsInstance(platform.create_screen_capture(), MSSCapture)

    def test_windows_modes_select_auto_native_and_mss(self) -> None:
        self.assertIsInstance(
            create_windows_capture(CaptureBackendMode.AUTO),
            FallbackCaptureBackend,
        )
        self.assertIsInstance(
            create_windows_capture(CaptureBackendMode.NATIVE),
            WindowsDXGICapture,
        )
        self.assertIsInstance(
            create_windows_capture(CaptureBackendMode.MSS),
            MSSCapture,
        )

    def test_macos_modes_select_auto_native_and_mss(self) -> None:
        self.assertIsInstance(
            create_macos_capture(CaptureBackendMode.AUTO),
            FallbackCaptureBackend,
        )
        self.assertIsInstance(
            create_macos_capture(CaptureBackendMode.NATIVE),
            ScreenCaptureKitCapture,
        )
        self.assertIsInstance(
            create_macos_capture(CaptureBackendMode.MSS),
            MSSCapture,
        )


if __name__ == "__main__":
    unittest.main()
