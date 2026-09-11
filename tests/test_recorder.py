"""Tests for local event persistence."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.intervention.recorder import EventRecorder, ProtectionEvent


class EventRecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "events.db"
        self.recorder = EventRecorder(self.database_path)

    def tearDown(self) -> None:
        self.recorder.close()
        self.temporary_directory.cleanup()

    def test_records_and_marks_minimal_event_metadata(self) -> None:
        event = ProtectionEvent(
            occurred_at="2026-09-12T00:00:00+00:00",
            trigger_type="vision",
            label="TEST_LABEL",
            confidence=0.91,
            monitor_index=2,
        )

        event_id = self.recorder.record_async(event).result(timeout=2)
        self.recorder.mark_intervention_shown(event_id)

        stored = self.recorder.recent()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].id, event_id)
        self.assertEqual(stored[0].monitor_index, 2)
        self.assertEqual(stored[0].label, "TEST_LABEL")
        self.assertAlmostEqual(stored[0].confidence or 0.0, 0.91)
        self.assertTrue(stored[0].intervention_shown)

    def test_database_schema_has_no_captured_content_fields(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(protection_events)"
                ).fetchall()
            }

        self.assertNotIn("screenshot", columns)
        self.assertNotIn("url", columns)
        self.assertNotIn("window_title", columns)
        self.assertEqual(
            columns,
            {
                "id",
                "occurred_at",
                "trigger_type",
                "label",
                "confidence",
                "monitor_index",
                "intervention_shown",
            },
        )

    def test_events_persist_after_reopening_database(self) -> None:
        self.recorder.record(
            ProtectionEvent(
                occurred_at="2026-09-12T01:00:00+00:00",
                trigger_type="vision",
                label=None,
                confidence=None,
                monitor_index=1,
            )
        )
        self.recorder.close()

        self.recorder = EventRecorder(self.database_path)

        self.assertEqual(len(self.recorder.recent()), 1)

    def test_recent_rejects_invalid_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit must be at least 1"):
            self.recorder.recent(0)


if __name__ == "__main__":
    unittest.main()
