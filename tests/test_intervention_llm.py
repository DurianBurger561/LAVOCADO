"""Tests for the optional, privacy-limited meditation LLM support."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from app.intervention.llm import (
    LLMClient,
    MeditationContext,
    fallback_questions,
    time_of_day,
    today_trigger_count,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class LLMTests(unittest.TestCase):
    def test_time_of_day_uses_coarse_buckets(self) -> None:
        self.assertEqual(time_of_day(2), "late_night")
        self.assertEqual(time_of_day(8), "morning")
        self.assertEqual(time_of_day(14), "afternoon")
        self.assertEqual(time_of_day(20), "evening")

    def test_no_key_uses_local_fallbacks(self) -> None:
        client = LLMClient()
        context = MeditationContext(2, "late_night")

        self.assertEqual(client.generate_questions(context), fallback_questions(context))
        line = client.generate_practice_line(
            context,
            [("user", "压力很大，睡不着")],
            [],
            0,
        )
        self.assertIn("吸气", line)

    def test_today_trigger_count_reads_only_event_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            with sqlite3.connect(data_dir / "events.db") as connection:
                connection.execute(
                    "CREATE TABLE protection_events (occurred_at TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO protection_events VALUES (?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
                connection.execute(
                    "INSERT INTO protection_events VALUES ('2000-01-01T00:00:00+00:00')"
                )

            self.assertEqual(today_trigger_count(data_dir), 1)

    def test_remote_payload_contains_only_allowed_context(self) -> None:
        captured: list[dict[str, object]] = []

        def opener(request: object, timeout: float) -> FakeResponse:
            del timeout
            data = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            captured.append(data)
            return FakeResponse(
                {"choices": [{"message": {"content": "先慢慢吸气，再呼气。"}}]}
            )

        client = LLMClient(
            api_key="test-key",
            endpoint="https://example.test/v1",
            model="test-model",
            opener=opener,
        )
        client.generate_practice_line(
            MeditationContext(4, "late_night"),
            [("assistant", "你现在感觉怎样？"), ("user", "压力很大")],
            [("assistant", "慢慢呼吸"), ("user", "慢慢呼吸")],
            1,
        )

        self.assertEqual(len(captured), 1)
        serialized = json.dumps(captured[0], ensure_ascii=False)
        self.assertIn("压力很大", serialized)
        self.assertIn("late_night", serialized)
        self.assertIn("今天第 4 次", serialized)
        for forbidden in ("pornhub", "chrome.exe", "window title", "monitor 2"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
