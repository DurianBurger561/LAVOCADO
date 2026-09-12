"""Tests for the command-line entry point."""

import io
import json
import sys
import threading
import unittest
from unittest.mock import Mock, patch

import main
from app.intervention.recorder import RecordedEvent


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
