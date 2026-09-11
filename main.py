"""Command-line entry point for LAVOCADO."""

from __future__ import annotations

import argparse
import sys
import threading


def positive_int(value: str) -> int:
    """Parse a positive integer for argparse."""

    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local, private screen intervention")
    subparsers = parser.add_subparsers(dest="command")

    protect = subparsers.add_parser("protect", help="start screen protection")
    protect.add_argument(
        "--control-stdin",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    subparsers.add_parser("dashboard", help="open the local control panel")

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

    for line in input_stream:
        if line.strip().casefold() == "stop":
            stop_event.set()
            return
    stop_event.set()


def run_protection(control_stdin: bool = False, input_stream=None) -> None:
    """Run the existing protection loop on the process main thread."""

    from app.service import LavocadoService

    service = LavocadoService()
    stop_event = threading.Event()
    if control_stdin:
        listener = threading.Thread(
            target=_listen_for_stop,
            args=(stop_event, input_stream or sys.stdin),
            daemon=True,
            name="lavocado-dashboard-control",
        )
        listener.start()

    print("LAVOCADO is watching all detected monitors. Press Ctrl+C to stop.")
    try:
        service.start(stop_event=stop_event)
    except KeyboardInterrupt:
        service.stop()
    print("LAVOCADO stopped.")


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


def show_events(limit: int) -> None:
    """Print recent events without requiring a graphical display."""

    from app.intervention.recorder import EventRecorder

    recorder = EventRecorder()
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
    args = build_parser().parse_args(argv)
    command = args.command or default_command()
    if command == "dashboard":
        from app.ui.dashboard import run_dashboard

        run_dashboard()
    elif command == "events":
        show_events(args.limit)
    else:
        run_protection(getattr(args, "control_stdin", False))


if __name__ == "__main__":
    main()
