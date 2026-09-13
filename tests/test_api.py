"""Tests for the explicit pywebview-facing Dashboard API."""

import json
import unittest

from app.intervention.recorder import RecordedEvent
from app.ui.api import DashboardAPI
from app.ui.controller import ProtectionStatus


class FakeController:
    def __init__(self) -> None:
        self.status = ProtectionStatus.STOPPED
        self.last_exit_code = None
        self.test_requests = 0

    def start(self) -> bool:
        if self.status is ProtectionStatus.RUNNING:
            return False
        self.status = ProtectionStatus.RUNNING
        return True

    def stop(self) -> bool:
        if self.status is not ProtectionStatus.RUNNING:
            return False
        self.status = ProtectionStatus.STOPPING
        return True

    def test_intervention(self) -> bool:
        if self.status is not ProtectionStatus.RUNNING:
            return False
        self.test_requests += 1
        return True


class FakeRecorder:
    def recent(self, limit: int):
        self.limit = limit
        return [
            RecordedEvent(
                id=7,
                occurred_at="2026-09-12T01:02:03+00:00",
                trigger_type="vision",
                label="TEST_LABEL",
                confidence=0.87,
                monitor_index=2,
                intervention_shown=True,
            )
        ]

    def count(self) -> int:
        return 1


class FakeDiagnostics:
    def snapshot(self):
        return {
            "protection_state": "MONITORING",
            "last_scan_ms": 123.4,
            "temporal": [0, 1, 1],
        }


class BrokenController(FakeController):
    def start(self) -> bool:
        raise OSError("private system detail")


class DashboardAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = FakeController()
        self.recorder = FakeRecorder()
        self.api = DashboardAPI(
            self.controller,
            self.recorder,
            FakeDiagnostics(),
        )

    def test_start_stop_and_test_intervention(self) -> None:
        started = self.api.start_protection()
        tested = self.api.test_intervention()
        stopped = self.api.stop_protection()

        self.assertTrue(started["changed"])
        self.assertTrue(tested["changed"])
        self.assertEqual(self.controller.test_requests, 1)
        self.assertTrue(stopped["changed"])
        self.assertEqual(stopped["status"], "Stopping")

    def test_status_events_and_diagnostics_are_json_serializable(self) -> None:
        payloads = [
            self.api.get_status(),
            self.api.get_events(500),
            self.api.get_diagnostics(),
        ]

        json.dumps(payloads)
        self.assertEqual(self.recorder.limit, 100)
        self.assertEqual(payloads[1]["events"][0]["label"], "TEST_LABEL")
        self.assertEqual(payloads[2]["diagnostics"]["temporal"], [0, 1, 1])

    def test_model_status_excludes_filesystem_paths(self) -> None:
        payload = self.api.get_model_status()

        json.dumps(payload)
        self.assertTrue(payload["ok"])
        serialized = json.dumps(payload).casefold()
        for forbidden in ("/home/", "c:\\", "640m.onnx", "screenshot"):
            self.assertNotIn(forbidden, serialized)
        ids = {row["id"] for row in payload["models"]}
        self.assertIn("nudenet_640m", ids)
        self.assertIn("viddexa_mini", ids)

    def test_unknown_model_download_is_rejected(self) -> None:
        result = self.api.download_optional_model("not-a-model")

        self.assertFalse(result["ok"])
        self.assertIn("Unknown", result["message"])

    def test_vision_settings_exclude_intent_modes(self) -> None:
        payload = self.api.get_vision_settings()

        json.dumps(payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["settings"]["detection_mode"]["id"], "visual_violation")
        self.assertEqual(payload["settings"]["intent_modes"], [])
        self.assertFalse(payload["settings"]["context_model"]["can_block"])

    def test_errors_are_returned_without_exposing_exception_text(self) -> None:
        api = DashboardAPI(BrokenController(), self.recorder, FakeDiagnostics())

        result = api.start_protection()

        self.assertFalse(result["ok"])
        self.assertIn("OSError", result["message"])
        self.assertNotIn("private system detail", result["message"])

    def test_api_payload_contains_no_captured_content(self) -> None:
        payload = json.dumps(
            {
                "events": self.api.get_events(),
                "diagnostics": self.api.get_diagnostics(),
            }
        ).casefold()

        for forbidden in ("screenshot", "original_frame", "model_frame", "crop"):
            self.assertNotIn(forbidden, payload)


if __name__ == "__main__":
    unittest.main()
