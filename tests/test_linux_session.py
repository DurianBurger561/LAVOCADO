"""Tests for Linux display-session and native-backend routing."""

import unittest

from app.platforms.capture.linux_session import (
    LinuxCaptureRoute,
    LinuxDisplayProtocol,
    LinuxSessionKind,
    detect_linux_session,
)


class LinuxSessionDetectionTests(unittest.TestCase):
    def test_wayland_declaration_wins_when_xwayland_display_also_exists(self) -> None:
        session = detect_linux_session(
            {
                "XDG_SESSION_TYPE": "wayland",
                "WAYLAND_DISPLAY": "wayland-0",
                "DISPLAY": ":0",
            },
            "generic-linux",
        )

        self.assertEqual(session.kind, LinuxSessionKind.WAYLAND)
        self.assertEqual(session.protocol, LinuxDisplayProtocol.WAYLAND)
        self.assertEqual(session.capture_route, LinuxCaptureRoute.PIPEWIRE_PORTAL)

    def test_x11_declaration_selects_xshm(self) -> None:
        session = detect_linux_session(
            {"XDG_SESSION_TYPE": "X11", "DISPLAY": ":1"},
            "generic-linux",
        )

        self.assertEqual(session.kind, LinuxSessionKind.X11)
        self.assertEqual(session.protocol, LinuxDisplayProtocol.X11)
        self.assertEqual(session.capture_route, LinuxCaptureRoute.XSHM)

    def test_display_variables_are_used_when_session_type_is_missing(self) -> None:
        wayland = detect_linux_session(
            {"WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0"},
            "generic-linux",
        )
        x11 = detect_linux_session({"DISPLAY": ":0"}, "generic-linux")

        self.assertEqual(wayland.capture_route, LinuxCaptureRoute.PIPEWIRE_PORTAL)
        self.assertEqual(x11.capture_route, LinuxCaptureRoute.XSHM)

    def test_wslg_keeps_wsl_identity_and_selects_compatible_protocol(self) -> None:
        wayland = detect_linux_session(
            {
                "WSL_DISTRO_NAME": "Ubuntu-24.04",
                "WAYLAND_DISPLAY": "wayland-0",
                "DISPLAY": ":0",
            },
            "microsoft-standard-WSL2",
        )
        x11 = detect_linux_session(
            {"WSL_INTEROP": "/run/WSL/1_interop", "DISPLAY": ":0"},
            "generic-linux",
        )

        self.assertEqual(wayland.kind, LinuxSessionKind.WSL)
        self.assertTrue(wayland.is_wsl)
        self.assertEqual(wayland.capture_route, LinuxCaptureRoute.PIPEWIRE_PORTAL)
        self.assertEqual(x11.kind, LinuxSessionKind.WSL)
        self.assertEqual(x11.capture_route, LinuxCaptureRoute.XSHM)

    def test_kernel_release_alone_can_identify_wsl(self) -> None:
        session = detect_linux_session({}, "6.6.87.2-microsoft-standard-WSL2")

        self.assertEqual(session.kind, LinuxSessionKind.WSL)
        self.assertEqual(session.protocol, LinuxDisplayProtocol.NONE)
        self.assertEqual(session.capture_route, LinuxCaptureRoute.MSS)

    def test_headless_or_tty_session_uses_portable_route(self) -> None:
        session = detect_linux_session(
            {"XDG_SESSION_TYPE": "tty", "DISPLAY": "  "},
            "generic-linux",
        )

        self.assertEqual(session.kind, LinuxSessionKind.UNKNOWN)
        self.assertFalse(session.is_wsl)
        self.assertEqual(session.protocol, LinuxDisplayProtocol.NONE)
        self.assertEqual(session.capture_route, LinuxCaptureRoute.MSS)


if __name__ == "__main__":
    unittest.main()
