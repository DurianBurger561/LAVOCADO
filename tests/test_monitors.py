"""Tests for cross-platform monitor selection."""

import unittest

from app.vision.monitors import monitor_geometry, select_monitor_index


class MonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 5120, "height": 1604},
            {
                "left": 2560,
                "top": 164,
                "width": 2560,
                "height": 1440,
                "is_primary": False,
            },
            {
                "left": 0,
                "top": 0,
                "width": 2560,
                "height": 1600,
                "is_primary": False,
            },
        ]

    def test_uses_origin_monitor_when_wslg_has_no_primary_flag(self) -> None:
        self.assertEqual(select_monitor_index(self.monitors), 2)

    def test_honours_an_explicit_monitor_override(self) -> None:
        self.assertEqual(select_monitor_index(self.monitors, 1), 1)

    def test_rejects_the_combined_virtual_monitor(self) -> None:
        with self.assertRaises(ValueError):
            select_monitor_index(self.monitors, 0)

    def test_builds_tk_geometry_with_monitor_offset(self) -> None:
        self.assertEqual(
            monitor_geometry(self.monitors[1]),
            "2560x1440+2560+164",
        )


if __name__ == "__main__":
    unittest.main()
