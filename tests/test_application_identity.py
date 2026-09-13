"""Native app identifiers are stable and never derived from window titles."""

import subprocess
import unittest

from app.context.application import application_from_window
from app.platforms.base import WindowInfo
from app.platforms.linux import LinuxWindowProvider
from app.platforms.macos import MacOSWindowProvider
from app.platforms.windows import WindowsWindowProvider
from tests.test_watcher import FakeKernel32, FakeUser32


class ApplicationIdentityTests(unittest.TestCase):
    def test_window_conversion_omits_private_title(self) -> None:
        window = WindowInfo(
            title="https://private.example/secret?q=token",
            app_name="Chrome",
            app_identifier="chrome.exe",
            window_id="123",
            process_id=42,
            left=2000,
            top=100,
            width=1000,
            height=800,
        )

        context = application_from_window(window, clock=lambda: 10.0)

        self.assertEqual(context.identifier, "chrome.exe")
        self.assertEqual(context.window_id, "123")
        self.assertEqual(context.process_id, 42)
        self.assertEqual(context.window_center, (2500, 500))
        self.assertNotIn("private.example", repr(context))
        self.assertIsNone(application_from_window(None))

    def test_windows_uses_executable_and_hwnd(self) -> None:
        window = WindowsWindowProvider(FakeUser32(), FakeKernel32()).active_window()

        self.assertEqual(window.app_identifier, "browser.exe")
        self.assertEqual(window.window_id, "123")
        self.assertEqual(window.process_id, 42)

    def test_macos_uses_bundle_id_only_when_frontmost_app_agrees(self) -> None:
        def runner(*_args, **_kwargs):
            return subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="Safari\x1fPrivate title\x1f10\x1f20\x1f800\x1f600\n",
                stderr="",
            )

        match = MacOSWindowProvider(
            runner=runner,
            identity_reader=lambda: ("Safari", "com.apple.Safari", 123),
        ).active_window()
        mismatch = MacOSWindowProvider(
            runner=runner,
            identity_reader=lambda: ("Chrome", "com.google.Chrome", 456),
        ).active_window()

        self.assertEqual(match.app_identifier, "com.apple.Safari")
        self.assertEqual(match.process_id, 123)
        self.assertIsNone(mismatch.app_identifier)
        self.assertIsNone(mismatch.process_id)

    def test_linux_prefers_desktop_app_id_and_preserves_x11_window_id(self) -> None:
        def runner(command, **_kwargs):
            if "-root" in command:
                output = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4200012\n"
            elif command[0] == "xwininfo":
                output = ""
            else:
                output = (
                    '_NET_WM_NAME(UTF8_STRING) = "Private title"\n'
                    'WM_CLASS(STRING) = "firefox", "Firefox"\n'
                    "_NET_WM_PID(CARDINAL) = 42\n"
                    '_GTK_APPLICATION_ID(UTF8_STRING) = "org.mozilla.firefox"\n'
                )
            return subprocess.CompletedProcess(command, 0, output, "")

        window = LinuxWindowProvider(
            runner=runner,
            executable_finder=lambda _name: "/usr/bin/tool",
            process_executable_reader=lambda _pid: "/usr/lib/firefox/firefox",
        ).active_window()

        self.assertEqual(window.app_identifier, "org.mozilla.firefox")
        self.assertEqual(window.window_id, "0x4200012")
        self.assertEqual(window.process_id, 42)

    def test_linux_uses_process_executable_but_never_window_class_as_fallback(self) -> None:
        def runner(command, **_kwargs):
            if "-root" in command:
                output = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4200012\n"
            elif command[0] == "xwininfo":
                output = ""
            else:
                output = (
                    'WM_CLASS(STRING) = "chrome", "Google Chrome"\n'
                    "_NET_WM_PID(CARDINAL) = 42\n"
                )
            return subprocess.CompletedProcess(command, 0, output, "")

        reader = lambda _pid: "/usr/bin/google-chrome-stable"
        known = LinuxWindowProvider(
            runner=runner,
            executable_finder=lambda _name: "/usr/bin/tool",
            process_executable_reader=reader,
        ).active_window()
        unknown = LinuxWindowProvider(
            runner=runner,
            executable_finder=lambda _name: "/usr/bin/tool",
            process_executable_reader=lambda _pid: None,
        ).active_window()

        self.assertEqual(known.app_identifier, "google-chrome-stable")
        self.assertIsNone(unknown.app_identifier)


if __name__ == "__main__":
    unittest.main()
