"""Command-line entry point for LAVOCADO Developer."""

from __future__ import annotations

import sys

import main as user_main
from app.build_edition import DEVELOPER_EDITION, set_build_edition


def main(argv=None) -> int | None:
    """Run the full user app, replacing only the dashboard with Developer Lab."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    set_build_edition(DEVELOPER_EDITION)
    if arguments[:1] == ["--benchmark-worker"]:
        if len(arguments) < 2:
            raise SystemExit("Missing benchmark worker kind")
        if arguments[1] == "capture":
            from developer.benchmark.capture_benchmark import main as worker_main
        elif arguments[1] == "stability":
            from developer.benchmark.capture_stability import main as worker_main
        elif arguments[1] == "diagnostic":
            from developer.benchmark.diagnostic_worker import main as worker_main
        else:
            raise SystemExit(f"Unknown benchmark worker: {arguments[1]}")
        raise SystemExit(worker_main(arguments[2:]))
    args = user_main.build_parser().parse_args(arguments)
    if args.self_check:
        from app.self_check import print_self_check

        return print_self_check(developer=True)
    if getattr(args, "overlay_process", False):
        user_main.main(arguments)
        return
    command = args.command or user_main.default_command()
    if command == "dashboard":
        from app.platforms import create_platform_adapter
        from developer.benchmark.ui.dashboard import run_developer_dashboard

        platform_adapter = create_platform_adapter()
        platform_adapter.prepare_environment()
        run_developer_dashboard(platform_adapter)
        return
    user_main.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
