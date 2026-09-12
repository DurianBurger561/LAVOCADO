"""Tests for privacy-safe in-memory protection diagnostics."""

import json
import unittest

from app.vision.diagnostics import DiagnosticsStore


def make_store() -> DiagnosticsStore:
    return DiagnosticsStore(
        model_variant="640m",
        inference_resolution=640,
        context_model="viddexa/nsfw-detection-2-mini",
        context_status="available",
    )


class DiagnosticsStoreTests(unittest.TestCase):
    def test_records_expected_scan_summary(self) -> None:
        store = make_store()
        store.set_protection_state("candidate")

        store.record_scan(
            monitor_index=2,
            elapsed_ms=183.26,
            scanned_at="2026-09-12T01:02:03.456+00:00",
            decision={
                "source": "nudenet_borderline_context",
                "nudenet_label": "FEMALE_BREAST_EXPOSED",
                "nudenet_score": 0.58,
                "threshold": 0.65,
                "context_label": "porn",
                "context_score": 0.91,
                "rescue_tile_index": None,
                "rescue_region": None,
            },
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
        self.assertEqual(snapshot["nudenet"]["status"], "context_confirmed")
        self.assertEqual(snapshot["context"], {"label": "porn", "score": 0.91})
        self.assertEqual(snapshot["decision_source"], "nudenet_borderline_context")
        self.assertEqual(snapshot["temporal"], [0, 1, 1])
        self.assertEqual(snapshot["rescue"]["pinned_tile_index"], 1)
        self.assertEqual(snapshot["monitors"]["2"]["last_scan_ms"], 183.3)

    def test_extracts_top_detection_without_retaining_checkpoints(self) -> None:
        store = make_store()

        store.record_scan(
            monitor_index=1,
            elapsed_ms=10,
            decision={
                "source": "nudenet_none",
                "check_points": [
                    {"class": "FACE_FEMALE", "score": 0.80, "box": [1, 2, 3, 4]},
                    {
                        "class": "FEMALE_BREAST_EXPOSED",
                        "score": 0.40,
                        "box": [5, 6, 7, 8],
                    },
                ],
            },
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
