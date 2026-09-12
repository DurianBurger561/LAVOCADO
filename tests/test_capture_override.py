"""Tests for the developer-only capture backend override."""

import sys
import unittest
from unittest.mock import patch

from app.platforms.capture import (
    CaptureBackendMode,
    CaptureUnavailableError,
    FallbackCaptureBackend,
    MSSCapture,
    PipeWirePortalCapture,
    ScreenCaptureKitCapture,
    WindowsDXGICapture,
    XShmCapture,
    create_linux_capture,
    create_macos_capture,
    create_windows_capture,
    detect_linux_session,
    resolve_capture_backend_mode,
)
from app.platforms.linux import LinuxPlatform
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
            LinuxPlatform(environ=dict(environment), release="generic-linux"),
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

    def test_linux_modes_select_auto_native_and_mss(self) -> None:
        wayland = detect_linux_session(
            {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"},
            "generic-linux",
        )
        x11 = detect_linux_session(
            {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
            "generic-linux",
        )

        self.assertIsInstance(
            create_linux_capture(wayland, mode=CaptureBackendMode.AUTO),
            FallbackCaptureBackend,
        )
        self.assertIsInstance(
            create_linux_capture(wayland, mode=CaptureBackendMode.NATIVE),
            PipeWirePortalCapture,
        )
        self.assertIsInstance(
            create_linux_capture(x11, mode=CaptureBackendMode.NATIVE),
            XShmCapture,
        )
        self.assertIsInstance(
            create_linux_capture(x11, mode=CaptureBackendMode.MSS),
            MSSCapture,
        )

    def test_forced_native_rejects_a_linux_session_without_native_route(self) -> None:
        session = detect_linux_session({}, "generic-linux")

        with self.assertRaisesRegex(CaptureUnavailableError, "Linux session"):
            create_linux_capture(session, mode=CaptureBackendMode.NATIVE)


if __name__ == "__main__":
    unittest.main()
