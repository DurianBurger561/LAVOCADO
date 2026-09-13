"""Compose the Developer dashboard: full user app plus Benchmark Lab."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app import config
from app.build_edition import DEVELOPER_APP_NAME
from app.context.settings import RuleSettingsStore
from app.intervention.recorder import EventRecorder
from app.platforms import PlatformAdapter
from app.ui.app_picker import ForegroundAppPicker
from app.ui.controller import ProtectionController
from app.ui.web_dashboard import dashboard_entry_path
from app.vision.model_assets import resource_root
from developer.benchmark.ui.api import DeveloperDashboardAPI

LAB_DIR = Path(__file__).resolve().parent


def lab_asset_dir(root: Path | None = None) -> Path:
    bundled = (resource_root() if root is None else Path(root)) / "developer" / "benchmark" / "ui"
    if (bundled / "lab.js").is_file():
        return bundled
    return LAB_DIR


def compose_developer_html(user_html: str, lab_html: str) -> str:
    html = user_html.replace("<title>LAVOCADO</title>", f"<title>{DEVELOPER_APP_NAME}</title>")
    html = html.replace(
        '<p class="eyebrow">LOCAL SCREEN PROTECTION</p>',
        '<p class="eyebrow">DEVELOPER EDITION</p>',
    )
    html = html.replace("<h1>LAVOCADO</h1>", f"<h1>{DEVELOPER_APP_NAME}</h1>")
    html = html.replace(
        '<link rel="stylesheet" href="styles.css">',
        '<link rel="stylesheet" href="styles.css">\n    <link rel="stylesheet" href="lab.css">',
    )
    html = html.replace(
        '<script src="app.js" defer></script>',
        '<script src="app.js" defer></script>\n    <script src="lab.js" defer></script>',
    )
    nav = """
      <nav id="edition-nav" class="edition-nav" aria-label="Developer edition">
        <button type="button" class="nav-button is-active" data-view="protection">Protection</button>
        <button type="button" class="nav-button" data-view="history">History</button>
        <button type="button" class="nav-button" data-view="settings">Settings</button>
        <button type="button" class="nav-button" data-view="developer">Developer</button>
      </nav>
"""
    html = html.replace('<div class="app-shell">', '<div class="app-shell">' + nav, 1)
    html = html.replace("</main>", lab_html + "\n      </main>", 1)
    return html


def prepare_developer_ui(root: Path | None = None) -> Path:
    user_entry = dashboard_entry_path(root)
    user_dir = user_entry.parent
    lab_dir = lab_asset_dir(root)
    temp_dir = Path(tempfile.mkdtemp(prefix="lavocado-developer-ui-"))
    shutil.copy2(user_dir / "styles.css", temp_dir / "styles.css")
    shutil.copy2(user_dir / "app.js", temp_dir / "app.js")
    shutil.copy2(lab_dir / "lab.css", temp_dir / "lab.css")
    shutil.copy2(lab_dir / "lab.js", temp_dir / "lab.js")
    html = compose_developer_html(
        user_entry.read_text(encoding="utf-8"),
        (lab_dir / "lab.html").read_text(encoding="utf-8"),
    )
    entry = temp_dir / "index.html"
    entry.write_text(html, encoding="utf-8")
    return entry


def run_developer_dashboard(
    platform_adapter: PlatformAdapter,
    *,
    webview_module=None,
    controller=None,
    recorder=None,
    rule_store=None,
    app_picker=None,
    root: Path | None = None,
) -> None:
    webview_gui = platform_adapter.prepare_webview_environment()
    if webview_module is None:
        try:
            import webview as webview_module
        except ImportError as error:
            raise RuntimeError(
                "pywebview is required; install requirements.txt"
            ) from error

    controller = controller or ProtectionController()
    recorder = recorder or EventRecorder(
        platform_adapter.default_data_dir() / "events.db"
    )
    rule_store = rule_store or RuleSettingsStore(
        platform_adapter.default_data_dir() / "events.db",
        legacy_blocked_apps=config.BLOCKED_APPS,
    )
    app_picker = app_picker or ForegroundAppPicker(
        platform_adapter.get_foreground_application
    )
    api = DeveloperDashboardAPI(
        controller,
        recorder,
        controller,
        rule_store,
        app_picker,
        data_dir=platform_adapter.default_data_dir(),
    )
    entry = prepare_developer_ui(root)
    closed = False

    def close_resources() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        try:
            controller.close()
        finally:
            try:
                app_picker.close()
            finally:
                recorder.close()
                shutil.rmtree(entry.parent, ignore_errors=True)

    window = webview_module.create_window(
        DEVELOPER_APP_NAME,
        str(entry),
        js_api=api,
        width=1180,
        height=780,
        min_size=(900, 640),
        background_color="#111827",
        text_select=True,
    )
    api.window = window
    window.events.closed += close_resources

    try:
        start_options: dict[str, object] = {
            "http_server": True,
            "private_mode": True,
        }
        if webview_gui is not None:
            start_options["gui"] = webview_gui
        webview_module.start(**start_options)
    finally:
        close_resources()
