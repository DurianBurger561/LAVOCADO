"""Tests for the process-scoped PlatformAdapter implementations."""

import ctypes
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.platforms import (
    UnsupportedPlatformError,
    WindowInfo,
    create_platform_adapter,
)
from app.platforms.capture import FallbackCaptureBackend, MSSCapture
from app.platforms.linux import LinuxPlatform, LinuxWindowProvider
from app.platforms.macos import MacOSPlatform, MacOSWindowProvider
from app.platforms.windows import (
    WindowsPlatform,
    WindowsWindowProvider,
    enable_dpi_awareness,
)
from app.platforms.website.windows_uia import WindowsUIAWebsiteReader
from app.platforms.website.macos_ax import MacOSAXWebsiteReader
from app.platforms.website.linux_atspi import LinuxAtspiWebsiteReader


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


class SuccessfulUser32:
    def __init__(self) -> None:
        self.context = None

    def SetProcessDpiAwarenessContext(self, context: object) -> int:
        self.context = context
        return 1


class LegacyUser32:
    def __init__(self) -> None:
        self.legacy_called = False

    def SetProcessDpiAwarenessContext(self, _context: object) -> int:
        return 0

    def SetProcessDPIAware(self) -> int:
        self.legacy_called = True
        return 1


class PlatformModuleTests(unittest.TestCase):
    def test_windows_adapter_creates_native_capture_with_mss_fallback(self) -> None:
        capture = WindowsPlatform(environ={}).create_screen_capture()

        self.assertIsInstance(capture, FallbackCaptureBackend)
        self.assertEqual(capture.status().preferred_backend, "windows_dxgi")

    def test_windows_adapter_creates_uia_website_reader(self) -> None:
        self.assertIsInstance(
            WindowsPlatform(environ={}).create_website_reader(),
            WindowsUIAWebsiteReader,
        )

    def test_macos_adapter_creates_native_capture_with_mss_fallback(self) -> None:
        capture = MacOSPlatform(environ={}).create_screen_capture()

        self.assertIsInstance(capture, FallbackCaptureBackend)
        self.assertEqual(
            capture.status().preferred_backend,
            "macos_screencapturekit",
        )

    def test_macos_adapter_creates_ax_website_reader(self) -> None:
        self.assertIsInstance(
            MacOSPlatform(environ={}).create_website_reader(),
            MacOSAXWebsiteReader,
        )

    def test_linux_x11_creates_xshm_capture_with_mss_fallback(self) -> None:
        capture = LinuxPlatform(
            environ={"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
            release="generic-linux",
        ).create_screen_capture()

        self.assertIsInstance(capture, FallbackCaptureBackend)
        self.assertEqual(capture.status().preferred_backend, "linux_xshm")

    def test_linux_unknown_session_remains_on_mss(self) -> None:
        capture = LinuxPlatform(
            environ={},
            release="generic-linux",
        ).create_screen_capture()

        self.assertIsInstance(capture, MSSCapture)

    def test_linux_adapter_creates_atspi_website_reader(self) -> None:
        self.assertIsInstance(
            LinuxPlatform(environ={}).create_website_reader(),
            LinuxAtspiWebsiteReader,
        )

    def test_wayland_uses_atspi_active_pid_when_x11_has_no_window(self) -> None:
        provider = Mock(active_window=Mock(return_value=None))
        adapter = LinuxPlatform(environ={}, window_provider=provider)
        with (
            patch("app.platforms.website.linux_atspi._NativeAtspiBridge") as bridge,
            patch("app.platforms.linux._linux_executable_for_pid", return_value="/usr/bin/firefox"),
        ):
            bridge.return_value.active_process_id.return_value = 42
            application = adapter.get_foreground_application()

        self.assertEqual(application.identifier, "firefox")
        self.assertEqual(application.process_id, 42)
        self.assertIsNone(application.window_id)

    def test_missing_linux_atspi_does_not_guess_application(self) -> None:
        adapter = LinuxPlatform(environ={}, window_provider=Mock(active_window=Mock(return_value=None)))
        with patch("app.platforms.website.linux_atspi._NativeAtspiBridge", side_effect=ImportError):
            self.assertIsNone(adapter.get_foreground_application())

    def test_linux_wayland_creates_portal_capture_with_mss_fallback(self) -> None:
        capture = LinuxPlatform(
            environ={
                "XDG_SESSION_TYPE": "wayland",
                "WAYLAND_DISPLAY": "wayland-0",
                "DISPLAY": ":0",
            },
            release="generic-linux",
        ).create_screen_capture()

        self.assertIsInstance(capture, FallbackCaptureBackend)
        self.assertEqual(
            capture.status().preferred_backend,
            "linux_pipewire_portal",
        )

    def test_linux_adapter_exposes_runtime_capture_route(self) -> None:
        platform = LinuxPlatform(
            environ={
                "WSL_DISTRO_NAME": "Ubuntu-24.04",
                "WAYLAND_DISPLAY": "wayland-0",
                "DISPLAY": ":0",
            },
            release="microsoft-standard-WSL2",
        )

        session = platform.desktop_session()

        self.assertEqual(session.kind.value, "wsl")
        self.assertEqual(session.capture_route.value, "pipewire_portal")

    def test_factory_returns_one_adapter_for_the_requested_system(self) -> None:
        self.assertIsInstance(create_platform_adapter("Windows"), WindowsPlatform)
        self.assertIsInstance(create_platform_adapter("Darwin"), MacOSPlatform)
        self.assertIsInstance(create_platform_adapter("Linux"), LinuxPlatform)

    def test_factory_rejects_an_unknown_system(self) -> None:
        with self.assertRaises(UnsupportedPlatformError):
            create_platform_adapter("Plan9")

    def test_each_adapter_owns_its_data_directory_policy(self) -> None:
        home = Path("/users/test")
        windows = WindowsPlatform(environ={}, home=home)
        macos = MacOSPlatform(environ={}, home=home)
        linux = LinuxPlatform(environ={}, home=home, release="generic-linux")

        self.assertEqual(
            windows.default_data_dir(),
            home / "AppData" / "Local" / "LAVOCADO",
        )
        self.assertEqual(
            macos.default_data_dir(),
            home / "Library" / "Application Support" / "LAVOCADO",
        )
        self.assertEqual(
            linux.default_data_dir(),
            home / ".local" / "share" / "lavocado",
        )

    def test_explicit_data_directory_override_has_priority(self) -> None:
        platform = LinuxPlatform(
            environ={"LAVOCADO_DATA_DIR": "/tmp/private-lavocado"},
            home=Path("/users/test"),
            release="generic-linux",
        )

        self.assertEqual(
            platform.default_data_dir(),
            Path("/tmp/private-lavocado"),
        )

    def test_native_data_directory_environment_variables_are_used(self) -> None:
        windows = WindowsPlatform(
            environ={"LOCALAPPDATA": "C:/Users/test/AppData/Local"},
            home=Path("C:/Users/test"),
        )
        linux = LinuxPlatform(
            environ={"XDG_DATA_HOME": "/tmp/xdg-data"},
            home=Path("/home/test"),
            release="generic-linux",
        )

        self.assertEqual(
            windows.default_data_dir(),
            Path("C:/Users/test/AppData/Local/LAVOCADO"),
        )
        self.assertEqual(
            linux.default_data_dir(),
            Path("/tmp/xdg-data/lavocado"),
        )

    def test_adapters_expose_platform_specific_setup_help(self) -> None:
        windows = WindowsPlatform(environ={})
        macos = MacOSPlatform(environ={})
        linux = LinuxPlatform(environ={}, release="generic-linux")

        self.assertIn("Tcl/Tk", windows.tkinter_help())
        self.assertIn("python.org", macos.tkinter_help())
        self.assertIn("python3-tk", linux.tkinter_help())
        self.assertIn("Privacy & Security", macos.screen_capture_help())
        self.assertIn("Wayland", linux.screen_capture_help())

    def test_windows_enables_per_monitor_dpi_awareness(self) -> None:
        user32 = SuccessfulUser32()

        self.assertTrue(enable_dpi_awareness(user32))
        self.assertIsNotNone(user32.context)

    def test_windows_falls_back_to_legacy_dpi_awareness(self) -> None:
        user32 = LegacyUser32()

        self.assertTrue(enable_dpi_awareness(user32))
        self.assertTrue(user32.legacy_called)

    def test_adapter_delegates_foreground_window_access(self) -> None:
        window = WindowInfo(title="Example", app_name="Browser")
        provider = Mock()
        provider.active_window.return_value = window
        platform = LinuxPlatform(
            environ={},
            release="generic-linux",
            window_provider=provider,
        )

        self.assertIs(platform.get_foreground_window(), window)
        provider.active_window.assert_called_once_with()

    def test_each_adapter_exposes_title_free_foreground_application(self) -> None:
        window = WindowInfo(
            title="Private page title",
            app_name="Chrome",
            app_identifier="chrome.exe",
            window_id="123",
            process_id=42,
        )
        for platform in (
            WindowsPlatform(environ={}, window_provider=Mock(active_window=Mock(return_value=window))),
            MacOSPlatform(environ={}, window_provider=Mock(active_window=Mock(return_value=window))),
            LinuxPlatform(environ={}, window_provider=Mock(active_window=Mock(return_value=window))),
        ):
            with self.subTest(platform=platform.name):
                application = platform.get_foreground_application()
                self.assertEqual(application.identifier, "chrome.exe")
                self.assertEqual(application.window_id, "123")
                self.assertEqual(application.process_id, 42)
                self.assertNotIn("Private page title", repr(application))

    def test_linux_explicitly_selects_the_qt_webview_backend(self) -> None:
        environment: dict[str, str] = {}
        platform = LinuxPlatform(
            environ=environment,
            release="generic-linux",
        )

        gui = platform.prepare_webview_environment()

        self.assertEqual(gui, "qt")
        self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", environment)

    def test_wsl_uses_software_rendering_without_overwriting_user_values(self) -> None:
        environment = {
            "WSL_DISTRO_NAME": "Ubuntu-24.04",
            "QT_OPENGL": "desktop",
        }
        platform = LinuxPlatform(environ=environment, release="microsoft-standard")

        gui = platform.prepare_webview_environment()

        self.assertEqual(gui, "qt")
        self.assertEqual(environment["QT_OPENGL"], "desktop")
        self.assertEqual(environment["LIBGL_ALWAYS_SOFTWARE"], "1")
        self.assertEqual(environment["QT_QUICK_BACKEND"], "software")
        self.assertIn("--disable-gpu", environment["QTWEBENGINE_CHROMIUM_FLAGS"])

    def test_native_platforms_keep_pywebviews_default_backend(self) -> None:
        self.assertIsNone(WindowsPlatform(environ={}).prepare_webview_environment())
        self.assertIsNone(MacOSPlatform(environ={}).prepare_webview_environment())

    def test_macos_overlay_joins_spaces_without_disabling_activation(self) -> None:
        class Root:
            def __init__(self) -> None:
                self._w = "."
                self.tk_calls: list[tuple[object, ...]] = []
                self.bindings: list[tuple[object, ...]] = []
                self.tk = self

            def call(self, *args: object) -> None:
                self.tk_calls.append(args)

            def title(self) -> str:
                return "LAVOCADO Protection"

            def bind(self, *args: object, **kwargs: object) -> None:
                self.bindings.append((*args, kwargs))

        root = Root()
        platform = MacOSPlatform(environ={})
        native_window = Mock()
        native_window.title.return_value = "LAVOCADO Protection"
        native_window.collectionBehavior.return_value = 8
        native_app = Mock()
        native_app.windows.return_value = [native_window]
        appkit = SimpleNamespace(
            NSApplication=SimpleNamespace(
                sharedApplication=Mock(return_value=native_app)
            ),
            NSApplicationActivationPolicyAccessory=1,
            NSWindowCollectionBehaviorCanJoinAllSpaces=1,
            NSWindowCollectionBehaviorCanJoinAllApplications=262144,
            NSWindowCollectionBehaviorFullScreenAuxiliary=256,
        )

        with patch.dict("sys.modules", {"AppKit": appkit}):
            platform.prepare_overlay_window(root)
        platform.release_overlay_focus()

        native_app.setActivationPolicy_.assert_called_once_with(1)
        native_window.setCollectionBehavior_.assert_called_once_with(
            8 | 1 | 262144 | 256
        )
        self.assertEqual(
            root.tk_calls,
            [
                ("wm", "attributes", ".", "-class", "nspanel"),
                (
                    "::tk::unsupported::MacWindowStyle",
                    "style",
                    ".",
                    "overlay",
                    ("canJoinAllSpaces", "nonActivating"),
                ),
            ],
        )
        self.assertEqual(root.bindings[0][0], "<Map>")

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
