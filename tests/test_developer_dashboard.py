"""Developer dashboard composes user assets plus Benchmark Lab."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.build_edition import DEVELOPER_APP_NAME
from app.platforms.linux import LinuxPlatform
from app.ui.api import DashboardAPI
from developer.benchmark.ui.api import DeveloperDashboardAPI
from developer.benchmark.ui.dashboard import (
    compose_developer_html,
    prepare_developer_ui,
    run_developer_dashboard,
)
try:
    from test_web_dashboard import FakeController, FakeRecorder, FakeWebview
except ImportError:
    from tests.test_web_dashboard import FakeController, FakeRecorder, FakeWebview

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DeveloperDashboardTests(unittest.TestCase):
    def test_composed_html_adds_lab_and_keeps_user_dashboard(self) -> None:
        user_html = (PROJECT_ROOT / "app" / "ui" / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        lab_html = (PROJECT_ROOT / "developer" / "benchmark" / "ui" / "lab.html").read_text(
            encoding="utf-8"
        )
        composed = compose_developer_html(user_html, lab_html)
        self.assertIn("LAVOCADO Developer", composed)
        self.assertIn("Benchmark Lab", composed)
        self.assertIn("Threshold profile", composed)
        self.assertIn("Proposal margin", composed)
        self.assertIn("Sweep proposal and strong", composed)
        self.assertIn("lab.js", composed)
        self.assertIn("Start protection", composed)
        self.assertNotIn("Medical whitelist", composed)

    def test_prepare_ui_copies_user_and_lab_assets(self) -> None:
        entry = prepare_developer_ui()
        try:
            directory = entry.parent
            self.assertTrue((directory / "styles.css").is_file())
            self.assertTrue((directory / "app.js").is_file())
            self.assertTrue((directory / "lab.js").is_file())
            self.assertTrue((directory / "lab.css").is_file())
            html = entry.read_text(encoding="utf-8")
            self.assertIn("edition-nav", html)
            self.assertIn("benchmark-lab", html)
        finally:
            import shutil

            shutil.rmtree(entry.parent, ignore_errors=True)

    def test_window_title_is_developer_edition(self) -> None:
        webview = FakeWebview()
        platform = LinuxPlatform(environ={}, release="generic-linux")
        run_developer_dashboard(
            platform,
            webview_module=webview,
            controller=FakeController(),
            recorder=FakeRecorder(),
            rule_store=object(),
        )
        args, options = webview.window_call
        self.assertEqual(args[0], DEVELOPER_APP_NAME)
        self.assertIsInstance(options["js_api"], DeveloperDashboardAPI)
        self.assertIsInstance(options["js_api"], DashboardAPI)

    def test_user_html_has_no_benchmark_lab(self) -> None:
        html = (PROJECT_ROOT / "app" / "ui" / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        script = (PROJECT_ROOT / "app" / "ui" / "web" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Benchmark Lab", html)
        self.assertNotIn("lab_start_run", script)
        self.assertNotIn("developer.benchmark", script)
