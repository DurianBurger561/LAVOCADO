"""Tests for the command-line entry point."""

import argparse
import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import main
from app.context.models import (
    ApplicationRule,
    ContextPolicyAction,
    WebsiteMatchMode,
    WebsiteRule,
)
from app.context.settings import RuleSettings, RuleSettingsStore
from app.intervention.recorder import RecordedEvent
from app.platforms.capture import MonitorInfo
from app.ui.overlay.monitor_payload import encode_monitor


class MainTests(unittest.TestCase):
    def test_parser_keeps_protection_as_default(self) -> None:
        self.assertIsNone(main.build_parser().parse_args([]).command)
        self.assertEqual(main.default_command(), "protect")

    def test_packaged_app_opens_dashboard_by_default(self) -> None:
        with patch.object(sys, "frozen", True, create=True):
            self.assertEqual(main.default_command(), "dashboard")

    def test_parser_accepts_dashboard_and_event_limit(self) -> None:
        dashboard = main.build_parser().parse_args(["dashboard"])
        events = main.build_parser().parse_args(["events", "--limit", "7"])

        self.assertEqual(dashboard.command, "dashboard")
        self.assertEqual(events.limit, 7)

    def test_parser_exposes_only_supported_commands(self) -> None:
        command_action = next(
            action
            for action in main.build_parser()._actions
            if isinstance(action, argparse._SubParsersAction)
        )

        self.assertEqual(
            set(command_action.choices),
            {"protect", "dashboard", "events"},
        )

    def test_dashboard_command_uses_webview(self) -> None:
        platform = Mock()
        with (
            patch(
                "main.create_platform_adapter",
                return_value=platform,
            ) as create_adapter,
            patch("app.ui.web_dashboard.run_web_dashboard") as run_dashboard,
        ):
            main.main(["dashboard"])

        create_adapter.assert_called_once_with()
        platform.prepare_environment.assert_called_once_with()
        run_dashboard.assert_called_once_with(platform)

    def test_protection_receives_the_process_platform_adapter(self) -> None:
        platform = Mock()
        with (
            patch("main.create_platform_adapter", return_value=platform),
            patch("main.run_protection") as run_protection,
        ):
            main.main(["protect"])

        platform.prepare_environment.assert_called_once_with()
        run_protection.assert_called_once_with(platform, False)

    def test_protection_loads_persisted_context_policy_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            RuleSettingsStore(data_dir / "events.db").save(RuleSettings(
                application_rules=(
                    ApplicationRule("chrome.exe", ContextPolicyAction.FORCE_BLOCK),
                ),
                website_rules=(WebsiteRule(
                    "blocked.example", ContextPolicyAction.FORCE_BLOCK,
                    WebsiteMatchMode.EXACT_HOST,
                ),),
            ))
            platform = Mock(default_data_dir=Mock(return_value=data_dir))
            with (
                patch("app.service.LavocadoService") as service_class,
                patch("sys.stdout", io.StringIO()),
            ):
                main.run_protection(platform)

        arguments, keywords = service_class.call_args
        self.assertEqual(arguments, (platform,))
        self.assertEqual(
            [rule.identifier for rule in keywords["context_policy"].application.rules],
            ["chrome.exe"],
        )
        self.assertEqual(
            [rule.domain for rule in keywords["context_policy"].website.rules],
            ["blocked.example"],
        )
        self.assertNotIn("watcher", keywords)

    def test_broken_rule_schema_falls_back_to_existing_protection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            with closing(sqlite3.connect(data_dir / "events.db")) as connection, connection:
                connection.execute("CREATE TABLE application_rules (broken TEXT)")
            platform = Mock(default_data_dir=Mock(return_value=data_dir))
            with (
                patch("app.service.LavocadoService") as service_class,
                patch("sys.stdout", io.StringIO()),
            ):
                main.run_protection(platform)

        service_class.assert_called_once_with(platform)

    def test_overlay_process_flag_runs_the_internal_entry_point(self) -> None:
        platform = Mock()
        monitor = MonitorInfo("display-b", 2, -1200, 0, 1200, 900)
        with (
            patch("main.create_platform_adapter", return_value=platform),
            patch("main.run_overlay") as run_overlay,
        ):
            main.main(["--overlay-process", "--overlay-monitor", encode_monitor(monitor)])

        platform.prepare_environment.assert_called_once_with()
        run_overlay.assert_called_once_with(monitor)

    def test_control_message_sets_stop_event(self) -> None:
        stop_event = threading.Event()

        main._listen_for_stop(stop_event, io.StringIO("ignore\nstop\n"))

        self.assertTrue(stop_event.is_set())

    def test_closed_control_pipe_sets_stop_event(self) -> None:
        stop_event = threading.Event()

        main._listen_for_stop(stop_event, io.StringIO(""))

        self.assertTrue(stop_event.is_set())

    def test_control_protocol_returns_diagnostics_and_queues_overlay(self) -> None:
        stop_event = threading.Event()
        test_event = threading.Event()
        output = io.StringIO()

        class Diagnostics:
            @staticmethod
            def snapshot():
                return {"protection_state": "MONITORING", "temporal": [1]}

        main._listen_for_control(
            stop_event,
            test_event,
            Diagnostics(),
            io.StringIO("diagnostics\ntest-intervention\nstop\n"),
            output,
        )

        self.assertTrue(stop_event.is_set())
        self.assertTrue(test_event.is_set())
        line = output.getvalue().strip()
        self.assertTrue(line.startswith(main.DIAGNOSTICS_PREFIX))
        payload = json.loads(line.removeprefix(main.DIAGNOSTICS_PREFIX))
        self.assertEqual(payload["temporal"], [1])

    def test_recovers_a_redirected_stream_for_windowed_builds(self) -> None:
        recovered = io.StringIO()
        opener = Mock(return_value=recovered)

        result = main._standard_stream(None, 1, "w", opener=opener)

        self.assertIs(result, recovered)
        opener.assert_called_once_with(
            1,
            "w",
            encoding="utf-8",
            closefd=False,
        )

    def test_keeps_an_available_standard_stream(self) -> None:
        existing = io.StringIO()

        self.assertIs(main._standard_stream(existing, 1, "w"), existing)

    def test_format_event_contains_only_expected_metadata(self) -> None:
        event = RecordedEvent(
            id=3,
            occurred_at="2026-09-12T01:02:03+00:00",
            trigger_type="vision",
            label="TEST_LABEL",
            confidence=0.876,
            monitor_index=2,
            intervention_shown=True,
        )

        line = main.format_event(event)

        self.assertIn("TEST_LABEL", line)
        self.assertIn("confidence=0.88", line)
        self.assertIn("monitor=2", line)
        self.assertNotIn("screenshot", line)
        self.assertNotIn("window_title", line)


if __name__ == "__main__":
    unittest.main()
