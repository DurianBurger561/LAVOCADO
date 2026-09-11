"""Tests for safe overlay dismissal."""

import unittest

from app.vision.overlay import Overlay


class FakeRoot:
    def __init__(self) -> None:
        self.destroy_count = 0

    def destroy(self) -> None:
        self.destroy_count += 1


class OverlayTests(unittest.TestCase):
    def test_dismiss_destroys_the_window(self) -> None:
        overlay = Overlay()
        root = FakeRoot()
        overlay._root = root

        overlay.dismiss()

        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_escape_uses_the_same_dismiss_path(self) -> None:
        overlay = Overlay()
        root = FakeRoot()
        overlay._root = root

        result = overlay._dismiss_from_event(object())

        self.assertEqual(result, "break")
        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)


if __name__ == "__main__":
    unittest.main()
