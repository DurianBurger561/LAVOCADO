"""Tests for foreground-window providers and blocklist matching."""

import ctypes
import subprocess
import unittest

from app.blocklist.watcher import WindowWatcher
from app.platforms import WindowInfo
from app.platforms.linux import LinuxWindowProvider
from app.platforms.macos import MacOSWindowProvider
from app.platforms.windows import WindowsWindowProvider


class FakePlatform:
    def __init__(self, window: WindowInfo | None) -> None:
        self.window = window
        self.call_count = 0

    def get_foreground_window(self) -> WindowInfo | None:
        self.call_count += 1
        return self.window


class FakeUser32:
    title = "Blocked Site - Browser"

    def GetForegroundWindow(self) -> int:
        return 123

    def GetWindowTextLengthW(self, _window_handle: int) -> int:
        return len(self.title)

    def GetWindowTextW(
        self,
        _window_handle: int,
        buffer: ctypes.Array[ctypes.c_wchar],
        _length: int,
    ) -> int:
        buffer.value = self.title
        return len(self.title)

    def GetWindowRect(self, _window_handle: int, rectangle_pointer: object) -> int:
        rectangle = rectangle_pointer._obj
        rectangle.left = 100
        rectangle.top = 200
        rectangle.right = 900
        rectangle.bottom = 800
        return 1

    def GetWindowThreadProcessId(
        self,
        _window_handle: int,
        process_id_pointer: object,
    ) -> int:
        process_id_pointer._obj.value = 42
        return 1


class FakeKernel32:
    def __init__(self) -> None:
        self.closed_handles: list[int] = []

    def OpenProcess(self, _access: int, _inherit: bool, _process_id: int) -> int:
        return 456

    def QueryFullProcessImageNameW(
        self,
        _process_handle: int,
        _flags: int,
        path_buffer: ctypes.Array[ctypes.c_wchar],
        _path_length_pointer: object,
    ) -> int:
        path_buffer.value = r"C:\Program Files\Browser\browser.exe"
        return 1

    def CloseHandle(self, process_handle: int) -> int:
        self.closed_handles.append(process_handle)
        return 1


class WindowWatcherTests(unittest.TestCase):
    def test_native_error_does_not_log_window_title_or_address(self) -> None:
        class BrokenPlatform:
            def get_foreground_window(self):
                raise RuntimeError("https://private.example/secret?q=confidential")

        watcher = WindowWatcher(BrokenPlatform(), ["private.example"])
        with self.assertLogs("app.blocklist.watcher", level="WARNING") as captured:
            result = watcher.check()

        self.assertFalse(result.blocked)
        self.assertNotIn("private.example", str(captured.output))
        self.assertNotIn("confidential", str(captured.output))

    def test_disabled_blocklist_does_not_read_window_metadata(self) -> None:
        platform = FakePlatform(WindowInfo("Private title"))
        watcher = WindowWatcher(platform, [])

        self.assertFalse(watcher.check().blocked)
        self.assertEqual(platform.call_count, 0)

    def test_matches_title_case_insensitively(self) -> None:
        window = WindowInfo("Video on EXAMPLE.COM", "Browser", 0, 0, 800, 600)
        watcher = WindowWatcher(FakePlatform(window), ["example.com"])

        result = watcher.check()

        self.assertTrue(result.blocked)
        self.assertEqual(result.matched_term, "example.com")
        self.assertEqual(result.window.center, (400, 300))

    def test_matches_application_name(self) -> None:
        window = WindowInfo("Home", "Steam", 0, 0, 800, 600)
        watcher = WindowWatcher(FakePlatform(window), ["steam"])

        self.assertTrue(watcher.check().blocked)

    def test_windows_provider_reads_title_and_bounds(self) -> None:
        kernel32 = FakeKernel32()
        window = WindowsWindowProvider(FakeUser32(), kernel32).active_window()

        self.assertIsNotNone(window)
        self.assertEqual(window.title, "Blocked Site - Browser")
        self.assertEqual(window.app_name, "browser")
        self.assertEqual(window.center, (500, 500))
        self.assertEqual(kernel32.closed_handles, [456])

    def test_macos_provider_parses_app_title_and_bounds(self) -> None:
        def runner(*_args: object, **_kwargs: object):
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="Safari\x1fBlocked Site\x1f10\x1f20\x1f800\x1f600\n",
                stderr="",
            )

        window = MacOSWindowProvider(runner=runner).active_window()

        self.assertIsNotNone(window)
        self.assertEqual(window.app_name, "Safari")
        self.assertEqual(window.title, "Blocked Site")
        self.assertEqual(window.center, (410, 320))

    def test_linux_provider_reads_x11_title_class_and_bounds(self) -> None:
        def runner(command: list[str], **_kwargs: object):
            if "-root" in command:
                stdout = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4200012\n"
            elif command[0] == "xwininfo":
                stdout = (
                    "  Absolute upper-left X:  100\n"
                    "  Absolute upper-left Y:  50\n"
                    "  Width: 1200\n"
                    "  Height: 800\n"
                )
            else:
                stdout = (
                    '_NET_WM_NAME(UTF8_STRING) = "Blocked Site"\n'
                    'WM_CLASS(STRING) = "browser", "Browser"\n'
                )
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=stdout,
                stderr="",
            )

        provider = LinuxWindowProvider(
            runner=runner,
            executable_finder=lambda _name: "/usr/bin/tool",
        )

        window = provider.active_window()

        self.assertIsNotNone(window)
        self.assertEqual(window.title, "Blocked Site")
        self.assertEqual(window.app_name, "Browser")
        self.assertEqual(window.center, (700, 450))


if __name__ == "__main__":
    unittest.main()
