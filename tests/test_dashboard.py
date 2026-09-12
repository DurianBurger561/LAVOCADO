"""Tests for pure dashboard presentation helpers."""

import unittest

from app.intervention.recorder import RecordedEvent
from app.ui.dashboard import event_to_row


class DashboardTests(unittest.TestCase):
    def test_event_row_formats_metadata_without_captured_content(self) -> None:
        event = RecordedEvent(
            id=4,
            occurred_at="2026-09-12T01:02:03+00:00",
            trigger_type="vision",
            label="TEST_LABEL",
            confidence=0.876,
            monitor_index=2,
            intervention_shown=True,
        )

        row = event_to_row(event)

        self.assertEqual(row[1:], ("vision", "TEST_LABEL", "0.88", "2", "Yes"))
        self.assertNotIn("screenshot", row)
        self.assertNotIn("window_title", row)

    def test_event_row_handles_optional_detection_values(self) -> None:
        event = RecordedEvent(
            id=5,
            occurred_at="2026-09-12T01:02:03",
            trigger_type="blocklist",
            label=None,
            confidence=None,
            monitor_index=1,
            intervention_shown=False,
        )

        self.assertEqual(
            event_to_row(event),
            ("2026-09-12 01:02:03", "blocklist", "-", "-", "1", "No"),
        )


if __name__ == "__main__":
    unittest.main()
