"""Tests for the explicit pywebview-facing Dashboard API."""

import json
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.intervention.recorder import RecordedEvent
from app.intervention.llm import LLMClient
from tests.test_intervention_llm import FakeResponse
from app.ui.api import DashboardAPI
from app.ui.controller import DIAGNOSTICS_PREFIX, ProtectionController, ProtectionStatus


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


class RestartingController(FakeController):
    def __init__(self, result: bool) -> None:
        super().__init__()
        self.status = ProtectionStatus.RUNNING
        self.result = result
        self.restart_calls = 0

    def restart(self) -> bool:
        self.restart_calls += 1
        return self.result


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

    def test_dashboard_reads_serialized_controller_snapshot(self) -> None:
        with TemporaryDirectory() as temporary:
            controller = ProtectionController(
                command=("protect",), data_dir=Path(temporary)
            )
            api = DashboardAPI(controller, self.recorder, controller)

            response = api.get_diagnostics()

        self.assertTrue(response["ok"])
        self.assertIsInstance(response["diagnostics"], dict)
        self.assertEqual(response["diagnostics"]["protection_state"], "STOPPED")
        json.dumps(response)

    def test_dashboard_reads_fresh_ipc_diagnostics(self) -> None:
        controller = ProtectionController(command=("protect",))
        api = DashboardAPI(controller, self.recorder, controller)

        for elapsed_ms in (40.0, 55.0):
            payload = {
                "protection_state": "MONITORING",
                "last_scan_ms": elapsed_ms,
                "last_scan_at": "2026-09-14T12:00:00+00:00",
            }
            self.assertTrue(
                controller._handle_output_line(
                    f"{DIAGNOSTICS_PREFIX}{json.dumps(payload)}\n"
                )
            )
            response = api.get_diagnostics()
            self.assertTrue(response["ok"])
            self.assertEqual(response["diagnostics"]["last_scan_ms"], elapsed_ms)

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
        result = self.api.download_model("not-a-model")

        self.assertFalse(result["ok"])
        self.assertIn("Unknown", result["message"])

    def test_download_all_models_returns_required_catalog(self) -> None:
        fake_rows = [
            {"id": "nudenet_640m", "status": "downloading", "required": True},
            {"id": "yolo11_nsfw_small", "status": "downloading", "required": True},
            {"id": "viddexa_nano", "status": "downloading", "required": True},
            {"id": "viddexa_mini", "status": "downloading", "required": True},
        ]
        with patch("app.ui.api.start_download_all", return_value=fake_rows):
            payload = self.api.download_all_models()

        json.dumps(payload)
        self.assertTrue(payload["ok"])
        ids = {row["id"] for row in payload["models"]}
        self.assertEqual(
            ids,
            {"nudenet_640m", "yolo11_nsfw_small", "viddexa_nano", "viddexa_mini"},
        )

    def test_vision_settings_exclude_intent_modes(self) -> None:
        payload = self.api.get_vision_settings()

        json.dumps(payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["settings"]["detection_mode"]["id"], "visual_violation")
        self.assertEqual(payload["settings"]["intent_modes"], [])
        self.assertFalse(payload["settings"]["context_model"]["can_block"])

    def test_llm_settings_never_return_the_api_key(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            api = DashboardAPI(self.controller, self.recorder, data_dir=data_dir)

            saved = api.save_llm_settings(
                {
                    "api_key": "secret-key",
                    "endpoint": "https://example.test/v1",
                    "model": "test-model",
                    "enabled": True,
                }
            )
            self.assertTrue(saved["ok"])
            self.assertTrue(saved["api_key_set"])
            self.assertEqual(saved["connection"]["state"], "unverified")
            self.assertEqual(saved["api_key_source"], "dashboard")
            self.assertNotIn("secret-key", json.dumps(saved))

            preserved = api.save_llm_settings(
                {"api_key": "", "endpoint": "https://example.test/v2"}
            )
            self.assertTrue(preserved["api_key_set"])
            self.assertEqual(preserved["endpoint"], "https://example.test/v2")
            self.assertEqual(json.loads((data_dir / "llm_settings.json").read_text())["api_key"], "secret-key")

            cleared = api.clear_llm_api_key()
            self.assertTrue(cleared["ok"])
            self.assertFalse(cleared["api_key_set"])
            self.assertNotIn("secret-key", json.dumps(cleared))

    def test_llm_conversation_language_is_saved_and_resolved(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            (data_dir / "ui-language.json").write_text(
                json.dumps({"language": "zh"}), encoding="utf-8"
            )
            api = DashboardAPI(self.controller, self.recorder, data_dir=data_dir)

            following = api.get_llm_settings()
            self.assertEqual(following["language"], "")
            self.assertEqual(following["language_in_use"], "zh")

            chosen = api.save_llm_settings({"language": "en"})
            self.assertEqual(chosen["language"], "en")
            self.assertEqual(chosen["language_in_use"], "en")
            self.assertEqual(
                json.loads((data_dir / "llm_settings.json").read_text())["language"], "en"
            )

            api.save_llm_settings({"language": "klingon"})
            self.assertEqual(api.get_llm_settings()["language"], "")

    def test_llm_probe_tests_saved_model_and_reports_failure_then_success(self) -> None:
        with TemporaryDirectory() as temporary:
            api = DashboardAPI(self.controller, self.recorder, data_dir=Path(temporary))
            api.save_llm_settings({"api_key": "fake-key", "model": "chosen-model"})
            captured = []
            fail = True
            def opener(request, timeout):
                captured.append(json.loads(request.data))
                if fail:
                    raise urllib.error.HTTPError("https://test", 401, "fake-key", {}, None)
                return FakeResponse({"choices": [{"message": {"content": "OK"}}]})
            with patch("app.intervention.llm.urllib.request.urlopen", side_effect=opener):
                failed = api.test_llm_connection()
                self.assertTrue(failed["ok"])
                self.assertEqual(failed["connection"]["state"], "fallback")
                self.assertEqual(failed["connection"]["reason"], "authentication")
                self.assertNotIn("fake-key", json.dumps(failed))
                fail = False
                passed = api.test_llm_connection()
            self.assertEqual(passed["connection"]["state"], "online")
            self.assertTrue(passed["connection"]["checked_at"])
            self.assertEqual(api.get_llm_settings()["connection"]["state"], "online")
            self.assertEqual(captured[0]["model"], "chosen-model")
            self.assertEqual(captured[0]["messages"], [{"role": "user", "content": "Reply with OK only."}])
            changed = api.save_llm_settings({"model": "different-model"})
            self.assertEqual(changed["connection"]["state"], "unverified")

    def test_disabled_llm_does_not_send_a_probe(self) -> None:
        with TemporaryDirectory() as temporary:
            api = DashboardAPI(self.controller, self.recorder, data_dir=Path(temporary))
            api.save_llm_settings({"api_key": "fake-key", "enabled": False})
            with patch("app.intervention.llm.urllib.request.urlopen") as request:
                result = api.test_llm_connection()
            request.assert_not_called()
            self.assertFalse(result["api_key_set"])
            self.assertEqual(result["connection"]["reason"], "no_key")

    def test_stale_probe_does_not_validate_new_connection(self) -> None:
        with TemporaryDirectory() as temporary:
            api = DashboardAPI(self.controller, self.recorder, data_dir=Path(temporary))
            api.save_llm_settings({"api_key": "fake-key", "model": "old"})
            def opener(request, timeout):
                api.save_llm_settings({"model": "new"})
                return FakeResponse({"choices": [{"message": {"content": "OK"}}]})
            with patch("app.intervention.llm.urllib.request.urlopen", side_effect=opener):
                result = api.test_llm_connection()
            self.assertEqual(result["model"], "new")
            self.assertEqual(result["connection"]["state"], "unverified")

    def test_save_reports_restart_only_after_controller_confirms_it(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for restarted in (True, False):
                controller = RestartingController(restarted)
                api = DashboardAPI(controller, self.recorder, data_dir=data_dir)

                result = api.save_vision_settings(
                    {"scan": {"normal_interval_ms": 1000}}
                )

                self.assertTrue(result["ok"])
                self.assertEqual(result["restarted"], restarted)
                self.assertEqual(controller.restart_calls, 1)
                self.assertEqual(
                    api.get_vision_settings()["settings"]["scan"]["normal_interval_ms"],
                    1000,
                )

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
