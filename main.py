"""Command-line entry point for LAVOCADO."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading

from app.platforms import PlatformAdapter, create_platform_adapter
from app.platforms.capture import MonitorInfo
from app.ui.controller import DIAGNOSTICS_PREFIX
from app.ui.overlay.monitor_payload import decode_monitor


def positive_int(value: str) -> int:
    """Parse a positive integer for argparse."""

    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def overlay_monitor_arg(value: str) -> MonitorInfo:
    try:
        return decode_monitor(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local, private screen intervention")
    subparsers = parser.add_subparsers(dest="command")

    protect = subparsers.add_parser("protect", help="start screen protection")
    protect.add_argument(
        "--control-stdin",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--overlay-process",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--overlay-monitor",
        type=overlay_monitor_arg,
        help=argparse.SUPPRESS,
    )

    subparsers.add_parser("dashboard", help="open the local WebView control panel")

    events = subparsers.add_parser("events", help="show recent local events")
    events.add_argument("--limit", type=positive_int, default=20)
    return parser


def default_command() -> str:
    """Open the dashboard when packaged, while preserving the source default."""

    if getattr(sys, "frozen", False):
        return "dashboard"
    return "protect"


def _listen_for_stop(stop_event, input_stream) -> None:
    """Translate a dashboard pipe message or closed pipe into a clean stop."""

    _listen_for_control(stop_event, None, None, input_stream, None)


def _listen_for_control(
    stop_event,
    test_intervention_event,
    diagnostics,
    input_stream,
    output_stream,
) -> None:
    """Handle the dashboard's fixed, portable child-process protocol."""

    for line in input_stream:
        command = line.strip().casefold()
        if command == "stop":
            stop_event.set()
            return
        if command == "test-intervention" and test_intervention_event is not None:
            test_intervention_event.set()
        elif command == "diagnostics" and diagnostics is not None:
            payload = json.dumps(
                diagnostics.snapshot(),
                ensure_ascii=True,
                separators=(",", ":"),
            )
            print(
                f"{DIAGNOSTICS_PREFIX}{payload}",
                file=output_stream,
                flush=True,
            )
    stop_event.set()


def _standard_stream(stream, descriptor: int, mode: str, opener=open):
    """Recover a redirected stream hidden by a windowed PyInstaller bootloader."""

    if stream is not None:
        return stream
    try:
        return opener(
            descriptor,
            mode,
            encoding="utf-8",
            closefd=False,
        )
    except (OSError, ValueError):
        return None


def _write_status(message: str, output_stream) -> None:
    if output_stream is not None:
        print(message, file=output_stream, flush=True)


def run_protection(
    platform_adapter: PlatformAdapter,
    control_stdin: bool = False,
    input_stream=None,
) -> None:
    """Run the existing protection loop on the process main thread."""

    control_input = input_stream if input_stream is not None else sys.stdin
    control_output = sys.stdout
    if control_stdin:
        control_input = _standard_stream(control_input, 0, "r")
        control_output = _standard_stream(control_output, 1, "w")
        if control_input is None or control_output is None:
            raise RuntimeError("Dashboard control pipes are unavailable")

    from app.context.policy.application import ApplicationPolicy
    from app.context.policy.resolver import ContextPolicyService
    from app.context.policy.website import WebsitePolicy
    from app.context.settings import RuleSettingsStore
    from app.service import LavocadoService

    try:
        settings = RuleSettingsStore(
            platform_adapter.default_data_dir() / "events.db",
        ).load()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        # A damaged rule schema must not disable vision.
        service = LavocadoService(platform_adapter)
    else:
        service = LavocadoService(
            platform_adapter,
            context_policy=ContextPolicyService(
                ApplicationPolicy(settings.application_rules),
                WebsitePolicy(settings.website_rules),
            ),
        )
    stop_event = threading.Event()
    test_intervention_event = threading.Event()
    if control_stdin:
        listener = threading.Thread(
            target=_listen_for_control,
            args=(
                stop_event,
                test_intervention_event,
                service.diagnostics,
                control_input,
                control_output,
            ),
            daemon=True,
            name="lavocado-dashboard-control",
        )
        listener.start()

    _write_status(
        "LAVOCADO is watching all detected monitors. Press Ctrl+C to stop.",
        control_output,
    )
    try:
        service.start(
            stop_event=stop_event,
            test_intervention_event=test_intervention_event,
        )
    except KeyboardInterrupt:
        service.stop()
    _write_status("LAVOCADO stopped.", control_output)


def run_overlay(monitor: MonitorInfo) -> None:
    """Run the isolated macOS overlay process."""

    from app.ui.overlay.process import run_overlay_process_child

    control_input = _standard_stream(sys.stdin, 0, "r")
    if control_input is None:
        raise RuntimeError("Overlay control pipe is unavailable")
    run_overlay_process_child(monitor, control_input)


def format_event(event) -> str:
    """Return one privacy-safe event line for terminal output."""

    confidence = "-" if event.confidence is None else f"{event.confidence:.2f}"
    monitor = str(event.monitor_index)
    label = event.label or "-"
    shown = "yes" if event.intervention_shown else "no"
    return (
        f"{event.occurred_at} | {event.trigger_type:<9} | {label:<28} | "
        f"confidence={confidence} monitor={monitor} intervention={shown}"
    )


def show_events(limit: int, platform_adapter: PlatformAdapter) -> None:
    """Print recent events without requiring a graphical display."""

    from app.intervention.recorder import EventRecorder

    recorder = EventRecorder(platform_adapter.default_data_dir() / "events.db")
    try:
        events = recorder.recent(limit)
    finally:
        recorder.close()

    if not events:
        print("No local intervention events recorded yet.")
        return
    for event in events:
        print(format_event(event))


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    platform_adapter = create_platform_adapter()
    if args.overlay_process:
        if args.overlay_monitor is None:
            parser.error("--overlay-monitor is required for the overlay process")
        platform_adapter.prepare_environment()
        run_overlay(args.overlay_monitor)
        return

    command = args.command or default_command()
    if command == "dashboard":
        from app.ui.web_dashboard import run_web_dashboard

        platform_adapter.prepare_environment()
        run_web_dashboard(platform_adapter)
    elif command == "events":
        show_events(args.limit, platform_adapter)
    else:
        platform_adapter.prepare_environment()
        run_protection(
            platform_adapter,
            getattr(args, "control_stdin", False),
        )


if __name__ == "__main__":
    main()
