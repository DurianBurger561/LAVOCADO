"""Tests for privacy-safe in-memory protection diagnostics."""

import json
import unittest

from app.context.models import (
    ApplicationContext,
    ContextPolicyAction,
    ContextPolicyResult,
    ForegroundContext,
    WebsiteContext,
    WebsiteContextState,
)
from app.platforms.capture import CaptureBackendStatus
from app.vision.diagnostics import DiagnosticsStore
from app.vision.violation_policy import (
    VisualViolationClassification,
    VisualViolationDecision,
)


def make_store() -> DiagnosticsStore:
    return DiagnosticsStore(
        model_variant="640m",
        inference_resolution=640,
        context_model="viddexa/nsfw-detection-2-mini",
        context_status="available",
    )


class DiagnosticsStoreTests(unittest.TestCase):
    def test_foreground_diagnostics_are_coarse_and_clear_when_unavailable(self) -> None:
        store = make_store()
        context = ForegroundContext(
            ApplicationContext(
                "chrome.exe", "Private Window Title", "chrome.exe", "42", 0.0
            ),
            True,
            WebsiteContext(
                WebsiteContextState.KNOWN, "chromium",
                "private.example/path?q=secret", "test", 0.0,
            ),
            0.0,
        )
        policy = ContextPolicyResult(
            ContextPolicyAction.FORCE_BLOCK,
            ContextPolicyAction.FULL_BYPASS,
            ContextPolicyAction.FORCE_BLOCK,
        )

        store.record_foreground_context(context, policy)
        self.assertEqual(store.snapshot()["foreground_context"], {
            "application_available": True,
            "is_browser": True,
            "website_state": "known",
            "application_rule": "full_bypass",
            "website_rule": "force_block",
            "effective_policy": "force_block",
            "vision_called": False,
        })
        serialized = json.dumps(store.snapshot())
        for forbidden in ("Private", "private.example", "secret", "chrome.exe"):
            self.assertNotIn(forbidden, serialized)

        store.record_foreground_context(None, None)
        self.assertEqual(store.snapshot()["foreground_context"], {
            "application_available": False,
            "is_browser": None,
            "website_state": "unavailable",
            "application_rule": "normal",
            "website_rule": "normal",
            "effective_policy": "normal",
            "vision_called": True,
        })

    def test_nonbrowser_and_effective_policy_override(self) -> None:
        store = make_store()
        context = ForegroundContext(
            ApplicationContext("code", "Code", "code", "1", 0.0),
            False, None, 0.0,
        )
        policy = ContextPolicyResult(
            ContextPolicyAction.NORMAL,
            ContextPolicyAction.NORMAL,
            ContextPolicyAction.NORMAL,
        )

        store.record_foreground_context(
            context, policy, effective_override=ContextPolicyAction.FORCE_BLOCK
        )

        foreground = store.snapshot()["foreground_context"]
        self.assertFalse(foreground["is_browser"])
        self.assertEqual(foreground["website_state"], "not_browser")
        self.assertEqual(foreground["effective_policy"], "force_block")
        self.assertFalse(foreground["vision_called"])

    def test_records_privacy_safe_capture_status(self) -> None:
        store = make_store()

        store.record_capture(
            CaptureBackendStatus(
                preferred_backend="windows_dxgi",
                active_backend="mss",
                fallback=True,
                fallback_reason="CaptureUnavailableError: DXGI unavailable",
                healthy=True,
                session=None,
                monitor_count=2,
                frame_age_ms=12.34,
            )
        )

        self.assertEqual(
            store.snapshot()["capture"],
            {
                "preferred_backend": "windows_dxgi",
                "active_backend": "mss",
                "fallback": True,
                "fallback_reason": (
                    "CaptureUnavailableError: DXGI unavailable"
                ),
                "healthy": True,
                "error": None,
                "session": None,
                "monitor_count": 2,
                "frame_age_ms": 12.3,
            },
        )

    def test_records_expected_scan_summary(self) -> None:
        store = make_store()
        store.set_protection_state("candidate")

        store.record_scan(
            monitor_index=2,
            elapsed_ms=183.26,
            scanned_at="2026-09-12T01:02:03.456+00:00",
            decision=VisualViolationDecision(
                classification=VisualViolationClassification.VIOLATION,
                evidence=(),
                reason_codes=("nudenet_roi",),
                primary_region=None,
                frame_sequence=1,
                label="FEMALE_BREAST_EXPOSED",
                confidence=0.80,
                threshold=0.65,
                context_label="porn",
                context_score=0.91,
                monitor_index=2,
            ),
            temporal=(False, True, True),
            rescue_status={
                "next_tile_index": 2,
                "pinned_tile_index": 1,
                "pinned_checks_remaining": 1,
            },
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["protection_state"], "CANDIDATE")
        self.assertEqual(snapshot["model"], "NudeNet 640m")
        self.assertEqual(snapshot["last_scan_ms"], 183.3)
        self.assertEqual(snapshot["monitor_index"], 2)
        self.assertEqual(snapshot["nudenet"]["status"], "roi_confirmed")
        self.assertEqual(snapshot["context"], {"label": "porn", "score": 0.91})
        self.assertEqual(snapshot["decision_source"], "nudenet_roi")
        self.assertEqual(snapshot["classification"], "violation")
        self.assertEqual(snapshot["temporal"], [0, 1, 1])
        self.assertEqual(snapshot["rescue"]["pinned_tile_index"], 1)
        self.assertEqual(snapshot["monitors"]["2"]["last_scan_ms"], 183.3)

    def test_extracts_top_detection_without_retaining_checkpoints(self) -> None:
        store = make_store()

        store.record_scan(
            monitor_index=1,
            elapsed_ms=10,
            decision=VisualViolationDecision(
                classification=VisualViolationClassification.CLEAR,
                evidence=(),
                reason_codes=("nudenet_none",),
                primary_region=None,
                frame_sequence=1,
                label="FACE_FEMALE",
                confidence=0.80,
            ),
            temporal=(),
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["nudenet"]["label"], "FACE_FEMALE")
        self.assertEqual(snapshot["nudenet"]["status"], "observed")
        self.assertNotIn("check_points", snapshot)
        self.assertNotIn("box", json.dumps(snapshot))

    def test_snapshot_is_json_serializable_and_isolated(self) -> None:
        store = make_store()
        first = store.snapshot()
        first["nudenet"]["label"] = "MUTATED"

        second = store.snapshot()

        self.assertIsNone(second["nudenet"]["label"])
        json.dumps(second)

    def test_schema_does_not_expose_sensitive_content_fields(self) -> None:
        store = make_store()
        serialized = json.dumps(store.snapshot()).lower()

        for forbidden in (
            "screenshot",
            "crop",
            "url",
            "window_title",
            "image_path",
            "pixels",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
