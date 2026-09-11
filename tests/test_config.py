"""Regression tests for application configuration."""

import re
import unittest

from app import config


class ConfigTests(unittest.TestCase):
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
        self.assertNotEqual(
            config.OVERLAY_BUTTON_LABEL,
            config.OVERLAY_BUTTON_TEXT_COLOR,
        )


if __name__ == "__main__":
    unittest.main()
