"""Regression tests for application configuration."""

import re
import unittest

from app import config


class ConfigTests(unittest.TestCase):
    def test_detection_baseline_uses_640_pixels(self) -> None:
        self.assertEqual(config.MODEL_FRAME_MAX_EDGE, 640)
        self.assertEqual(config.NUDENET_INFERENCE_RESOLUTION, 640)

    def test_context_model_is_revision_pinned(self) -> None:
        self.assertEqual(
            config.CONTEXT_MODEL_NAME,
            "viddexa/nsfw-detection-2-mini",
        )
        self.assertRegex(config.CONTEXT_MODEL_REVISION, re.compile(r"^[0-9a-f]{40}$"))

    def test_overlay_colours_are_hex_values(self) -> None:
        colour_names = (
            "OVERLAY_BG",
            "OVERLAY_TITLE_COLOR",
            "OVERLAY_TEXT_COLOR",
            "OVERLAY_BUTTON_BG",
            "OVERLAY_BUTTON_TEXT_COLOR",
        )

        for name in colour_names:
            with self.subTest(name=name):
                value = getattr(config, name)
                self.assertRegex(value, re.compile(r"^#[0-9a-fA-F]{6}$"))

    def test_button_label_is_not_used_as_its_colour(self) -> None:
        for label in (
            config.OVERLAY_WAIT_BUTTON_LABEL,
            config.OVERLAY_READY_BUTTON_LABEL,
        ):
            with self.subTest(label=label):
                self.assertNotEqual(label, config.OVERLAY_BUTTON_TEXT_COLOR)


if __name__ == "__main__":
    unittest.main()
