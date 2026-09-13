"""Tests for pywebview dashboard composition and static resources."""

import tempfile
import unittest
from pathlib import Path

from app.platforms.linux import LinuxPlatform
from app.ui.api import DashboardAPI
from app.ui.web_dashboard import dashboard_entry_path, run_web_dashboard

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "app" / "ui" / "web"


class EventHook:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self) -> None:
        self.events = type("Events", (), {"closed": EventHook()})()


class FakeWebview:
    def __init__(self) -> None:
        self.window = FakeWindow()
        self.window_call = None
        self.start_call = None

    def create_window(self, *args, **kwargs):
        self.window_call = (args, kwargs)
        return self.window

    def start(self, **kwargs) -> None:
        self.start_call = kwargs


class FakeController:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class FakeRecorder:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class WebDashboardTests(unittest.TestCase):
    def test_source_dashboard_entry_exists(self) -> None:
        self.assertEqual(
            dashboard_entry_path(),
            (WEB_ROOT / "index.html").resolve(),
        )

    def test_entry_path_supports_a_frozen_resource_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = root / "app" / "ui" / "web" / "index.html"
            entry.parent.mkdir(parents=True)
            entry.touch()

            self.assertEqual(dashboard_entry_path(root), entry.resolve())

    def test_missing_entry_fails_with_a_clear_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            self.assertRaisesRegex(RuntimeError, "resource is missing"),
        ):
            dashboard_entry_path(Path(temp_dir))

    def test_composes_private_webview_and_closes_resources_once(self) -> None:
        webview = FakeWebview()
        controller = FakeController()
        recorder = FakeRecorder()
        platform = LinuxPlatform(environ={}, release="generic-linux")

        run_web_dashboard(
            platform,
            webview_module=webview,
            controller=controller,
            recorder=recorder,
            rule_store=object(),
        )

        args, options = webview.window_call
        self.assertEqual(args[0], "LAVOCADO")
        self.assertTrue(Path(args[1]).is_absolute())
        self.assertIsInstance(options["js_api"], DashboardAPI)
        self.assertEqual(options["min_size"], (850, 600))
        self.assertEqual(
            webview.start_call,
            {"http_server": True, "private_mode": True, "gui": "qt"},
        )
        self.assertEqual(len(webview.window.events.closed.handlers), 1)
        webview.window.events.closed.handlers[0]()
        self.assertEqual(controller.closed, 1)
        self.assertEqual(recorder.closed, 1)

    def test_frontend_waits_for_bridge_and_uses_only_explicit_api(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn('href="styles.css"', html)
        self.assertIn('src="app.js"', html)
        self.assertIn('addEventListener("pywebviewready"', script)
        for method in (
            "start_protection",
            "stop_protection",
            "get_status",
            "get_events",
            "get_diagnostics",
            "test_intervention",
            "get_rules",
            "add_rule",
            "remove_rule",
            "get_vision_settings",
        ):
            self.assertIn(method, script)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("eval(", script)

    def test_dashboard_has_four_rule_groups_and_whitelist_confirmation(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        for group in (
            "blocked_applications", "whitelisted_applications",
            "blocked_websites", "whitelisted_websites",
        ):
            self.assertIn(f'data-rule-group="{group}"', html)
            self.assertIn(f'"{group}"', script)
        self.assertIn('id="rule-confirmation"', html)
        self.assertIn("Visual protection will be completely disabled", script)
        self.assertIn("You are responsible for content", script)
        self.assertIn("medical, educational, artistic, news", script)
        self.assertIn("LAVOCADO does not determine viewing intent", html)
        self.assertIn('id="vision-settings-heading"', html)
        self.assertIn("VISUAL DETECTION", html)
        self.assertIn("There is no medical, art, education, or news mode.", html)
        self.assertNotIn("Medical Mode", html)
        self.assertNotIn("Art Mode", html)
        self.assertNotIn("Education Mode", html)
        self.assertEqual(html.count('class="button ghost pick-app"'), 2)
        self.assertIn('"begin_app_pick"', script)
        self.assertIn('"get_app_pick_result"', script)

    def test_dashboard_renders_capture_backend_diagnostics(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        for field in (
            "capture-mode",
            "capture-preferred",
            "capture-active",
            "capture-fallback",
            "capture-reason",
            "capture-frame-age",
            "capture-monitors",
        ):
            with self.subTest(field=field):
                self.assertIn(f'id="{field}"', html)
                self.assertIn(f'"{field}"', script)

    def test_dashboard_renders_coarse_foreground_context(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        for field in (
            "foreground-application", "foreground-browser", "foreground-website",
            "foreground-app-rule", "foreground-website-rule", "foreground-effective",
            "foreground-policy", "foreground-vision-called",
        ):
            with self.subTest(field=field):
                self.assertIn(f'id="{field}"', html)
                self.assertIn(f'"{field}"', script)
        self.assertIn("data.foreground_context", script)

    def test_dashboard_renders_vision_settings_group(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        for field in (
            "vision-primary-detector",
            "vision-context-model",
            "vision-detection-mode",
            "vision-thresholds",
            "vision-tile",
            "vision-roi",
            "vision-temporal",
        ):
            with self.subTest(field=field):
                self.assertIn(f'id="{field}"', html)
                self.assertIn(f'"{field}"', script)
        self.assertIn('"get_vision_settings"', script)
        self.assertIn("decision-classification", script)

    def test_dashboard_names_native_and_mss_capture_modes(self) -> None:
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        for label in (
            "Native · ${captureBackendName(backend)}",
            "MSS · Fallback",
            "MSS · Active",
            "Windows DXGI",
            "macOS ScreenCaptureKit",
            "Linux PipeWire Portal",
            "Linux XShm",
        ):
            with self.subTest(label=label):
                self.assertIn(label, script)

    def test_runtime_dependencies_include_platform_webview_backends(self) -> None:
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("pywebview>=6.2,<7", requirements)
        self.assertIn('sys_platform == "linux"', requirements)

    def test_pyinstaller_spec_bundles_all_web_resources(self) -> None:
        spec = (PROJECT_ROOT / "lavocado.spec").read_text(encoding="utf-8")

        self.assertIn('"app" / "ui" / "web"', spec)
        self.assertIn('"app/ui/web"', spec)

    def test_windows_packaging_includes_generated_uia_interface(self) -> None:
        spec = (PROJECT_ROOT / "lavocado.spec").read_text(encoding="utf-8")
        self.assertIn('GetModule("UIAutomationCore.dll")', spec)
        self.assertIn('"comtypes.gen.UIAutomationClient"', spec)

    def test_macos_packaging_includes_accessibility_framework(self) -> None:
        spec = (PROJECT_ROOT / "lavocado.spec").read_text(encoding="utf-8")
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn('"ApplicationServices"', spec)
        self.assertIn('pyobjc-framework-ApplicationServices', requirements)

    def test_linux_packaging_includes_atspi_reader(self) -> None:
        spec = (PROJECT_ROOT / "lavocado.spec").read_text(encoding="utf-8")
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn('"gi.repository.Atspi"', spec)
        self.assertIn('get_gi_typelibs(', spec)
        self.assertIn('PyGObject>=3.50', requirements)


if __name__ == "__main__":
    unittest.main()
