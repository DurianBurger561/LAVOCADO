"""Developer entry keeps user commands and swaps only the dashboard."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import developer_main
from app.build_edition import USER_EDITION, set_build_edition


class DeveloperMainTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_build_edition(USER_EDITION)

    def test_dashboard_uses_developer_dashboard(self) -> None:
        platform = Mock()
        with (
            patch(
                "app.platforms.create_platform_adapter",
                return_value=platform,
            ),
            patch(
                "developer.benchmark.ui.dashboard.run_developer_dashboard"
            ) as run_dashboard,
            patch("main.main") as user_main,
        ):
            developer_main.main(["dashboard"])

        platform.prepare_environment.assert_called_once_with()
        run_dashboard.assert_called_once_with(platform)
        user_main.assert_not_called()

    def test_protect_reuses_user_entry(self) -> None:
        with patch("main.main") as user_main:
            developer_main.main(["protect"])
        user_main.assert_called_once_with(["protect"])
