"""Command-line entry point for LAVOCADO Developer."""

from __future__ import annotations

from app.build_edition import DEVELOPER_EDITION, set_build_edition
import main as user_main


def main(argv=None) -> None:
    """Run the full user app, replacing only the dashboard with Developer Lab."""

    set_build_edition(DEVELOPER_EDITION)
    args = user_main.build_parser().parse_args(argv)
    if getattr(args, "overlay_process", False):
        user_main.main(argv)
        return
    command = args.command or user_main.default_command()
    if command == "dashboard":
        from app.platforms import create_platform_adapter
        from developer.benchmark.ui.dashboard import run_developer_dashboard

        platform_adapter = create_platform_adapter()
        platform_adapter.prepare_environment()
        run_developer_dashboard(platform_adapter)
        return
    user_main.main(argv)


if __name__ == "__main__":
    main()
