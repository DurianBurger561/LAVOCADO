"""Tests for local event persistence."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
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

    def test_marks_intervention_shown_asynchronously(self) -> None:
        event_id = self.recorder.record(
            ProtectionEvent(
                occurred_at="2026-09-12T00:00:00+00:00",
                trigger_type="vision",
                label=None,
                confidence=None,
                monitor_index=1,
            )
        )

        self.recorder.mark_intervention_shown_async(event_id).result(timeout=2)

        self.assertTrue(self.recorder.recent()[0].intervention_shown)

    def test_identity_rule_labels_are_never_persisted(self) -> None:
        for trigger_type in ("application_rule", "website_rule"):
            self.recorder.record(ProtectionEvent(
                occurred_at="2026-09-12T00:00:00+00:00",
                trigger_type=trigger_type,
                label="https://private.example/secret?q=confidential",
                confidence=None,
                monitor_index=1,
            ))

        self.assertEqual([event.label for event in self.recorder.recent()], [
            None, None,
        ])
        database_bytes = self.database_path.read_bytes()
        self.assertNotIn(b"private.example", database_bytes)
        self.assertNotIn(b"confidential", database_bytes)

    def test_old_identity_labels_are_hidden_without_modifying_history(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                "INSERT INTO protection_events (occurred_at, trigger_type, label, "
                "monitor_index) VALUES (?, ?, ?, ?)",
                ("2026-09-12T00:00:00+00:00", "website_rule", "private.example", 1),
            )

        self.assertIsNone(self.recorder.recent()[0].label)
        self.assertIn(b"private.example", self.database_path.read_bytes())

    def test_historical_blocklist_labels_are_hidden_without_modifying_history(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                "INSERT INTO protection_events (occurred_at, trigger_type, label, "
                "monitor_index) VALUES (?, ?, ?, ?)",
                ("2026-09-12T00:00:00+00:00", "blocklist", "Steam", 1),
            )

        self.assertIsNone(self.recorder.recent()[0].label)
        self.assertIn(b"Steam", self.database_path.read_bytes())

    def test_database_schema_has_no_captured_content_fields(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
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

    def test_count_returns_total_recorded_events(self) -> None:
        for hour in range(3):
            self.recorder.record(
                ProtectionEvent(
                    occurred_at=f"2026-09-12T0{hour}:00:00+00:00",
                    trigger_type="vision",
                    label=None,
                    confidence=None,
                    monitor_index=1,
                )
            )

        self.assertEqual(self.recorder.count(), 3)

    def test_close_releases_the_database_file(self) -> None:
        self.recorder.close()

        self.database_path.unlink()

        self.assertFalse(self.database_path.exists())


if __name__ == "__main__":
    unittest.main()
