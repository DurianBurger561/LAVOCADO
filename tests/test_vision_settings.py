"""Vision settings stay separate from context policy and have no intent modes."""

import json
import unittest

from app.vision.settings import vision_settings_snapshot


class VisionSettingsTests(unittest.TestCase):
    def test_snapshot_covers_the_vision_settings_group(self) -> None:
        snapshot = vision_settings_snapshot()

        self.assertEqual(snapshot["primary_detector"], "nudenet")
        self.assertEqual(snapshot["primary_detectors"], ["nudenet"])
        self.assertFalse(snapshot["yolo"]["requested"])
        self.assertTrue(snapshot["yolo"]["maps_sexual_act"])
        self.assertEqual(snapshot["context_model"]["role"], "tile_ranking")
        self.assertFalse(snapshot["context_model"]["can_block"])
        self.assertEqual(snapshot["detection_mode"]["id"], "visual_violation")
        self.assertFalse(snapshot["detection_mode"]["evaluates_viewing_intent"])
        self.assertIn("FEMALE_GENITALIA_EXPOSED", snapshot["thresholds"])
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
