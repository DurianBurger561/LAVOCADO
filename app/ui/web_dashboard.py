"""Compose the local pywebview dashboard."""

from __future__ import annotations

from pathlib import Path

from app.context.settings import RuleSettingsStore
from app.intervention.recorder import EventRecorder
from app.platforms import PlatformAdapter
from app.ui.api import DashboardAPI
from app.ui.app_picker import ForegroundAppPicker
from app.ui.controller import ProtectionController
from app.vision.model_assets import resource_root


def dashboard_entry_path(root: Path | None = None) -> Path:
    """Return the source or bundled dashboard HTML entry point."""

    base = resource_root() if root is None else Path(root)
    entry = base / "app" / "ui" / "web" / "index.html"
    if not entry.is_file():
        raise RuntimeError(f"Dashboard resource is missing: {entry}")
    return entry.resolve()


def run_web_dashboard(
    platform_adapter: PlatformAdapter,
    *,
    webview_module=None,
    controller=None,
    recorder=None,
    rule_store=None,
    app_picker=None,
    root: Path | None = None,
) -> None:
    """Open the local web dashboard on the GUI main thread."""

    webview_gui = platform_adapter.prepare_webview_environment()
    if webview_module is None:
        try:
            import webview as webview_module
        except ImportError as error:
            raise RuntimeError(
                "pywebview is required; install requirements.txt"
            ) from error

    controller = controller or ProtectionController(
        data_dir=platform_adapter.default_data_dir()
    )
    recorder = recorder or EventRecorder(
        platform_adapter.default_data_dir() / "events.db"
    )
    rule_store = rule_store or RuleSettingsStore(
        platform_adapter.default_data_dir() / "events.db",
    )
    app_picker = app_picker or ForegroundAppPicker(
        platform_adapter.get_foreground_application
    )
    api = DashboardAPI(
        controller,
        recorder,
        controller,
        rule_store,
        app_picker,
        data_dir=platform_adapter.default_data_dir(),
    )
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

    window = webview_module.create_window(
        "LAVOCADO",
        str(dashboard_entry_path(root)),
        js_api=api,
        width=1050,
        height=720,
        min_size=(850, 600),
        background_color="#111827",
        text_select=True,
    )
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
