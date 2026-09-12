"""pywebview dashboard composition while the Tk dashboard remains available."""

from __future__ import annotations

from pathlib import Path

from app.intervention.recorder import EventRecorder
from app.platforms import PlatformAdapter
from app.ui.api import DashboardAPI
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

    controller = controller or ProtectionController()
    recorder = recorder or EventRecorder(
        platform_adapter.default_data_dir() / "events.db"
    )
    api = DashboardAPI(controller, recorder, controller)
    closed = False

    def close_resources() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        try:
            controller.close()
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
