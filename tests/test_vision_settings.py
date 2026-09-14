"""Vision settings stay separate from context policy and have no intent modes."""

import json
import unittest
from unittest.mock import patch

from app.settings.schema import default_vision_settings, merge_vision_settings
from app.vision.settings import vision_settings_snapshot


class VisionSettingsTests(unittest.TestCase):
    def test_yolo_status_depends_on_saved_primary_not_model_path(self) -> None:
        settings = default_vision_settings()
        with patch.dict("os.environ", {"LAVOCADO_YOLO_MODEL": "/unused/yolo.pt"}):
            self.assertFalse(vision_settings_snapshot(settings)["yolo"]["requested"])
            selected = merge_vision_settings(
                settings, {"detector": {"primary": "yolo11_nsfw_small"}}
            )
            self.assertTrue(vision_settings_snapshot(selected)["yolo"]["requested"])

    def test_snapshot_covers_the_vision_settings_group(self) -> None:
        snapshot = vision_settings_snapshot()

        self.assertEqual(snapshot["primary_detector"], "nudenet_640m")
        self.assertEqual(snapshot["primary_detectors"], ["nudenet_640m"])
        self.assertFalse(snapshot["yolo"]["requested"])
        self.assertTrue(snapshot["yolo"]["maps_sexual_act"])
        self.assertEqual(snapshot["context_model"]["role"], "tile_ranking")
        self.assertFalse(snapshot["context_model"]["can_block"])
        self.assertEqual(snapshot["detection_mode"]["id"], "visual_violation")
        self.assertFalse(snapshot["detection_mode"]["evaluates_viewing_intent"])
        self.assertIn(
            "FEMALE_GENITALIA_EXPOSED",
            snapshot["thresholds"]["nudenet_640m"],
        )
        self.assertIn("breast", snapshot["thresholds"]["yolo11_nsfw_small"])
        self.assertIn("proposal", snapshot["thresholds"]["nudenet_640m"]["FEMALE_BREAST_EXPOSED"])
        self.assertIn("strong", snapshot["thresholds"]["yolo11_nsfw_small"]["breast"])
        self.assertEqual(snapshot["tile"]["rows"] * snapshot["tile"]["columns"], 4)
        self.assertEqual(snapshot["temporal"]["required_hits"], 2)
        self.assertEqual(snapshot["intent_modes"], [])
        json.dumps(snapshot)

    def test_snapshot_has_no_viewing_intent_modes(self) -> None:
        serialized = json.dumps(vision_settings_snapshot()).casefold()

        for forbidden in ("medical mode", "art mode", "education mode", "news mode"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
