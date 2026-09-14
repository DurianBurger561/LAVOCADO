"""Canonical monitor geometry is shared by capture and the overlay child."""

import json
import unittest

from app.platforms.capture import MonitorInfo
from app.ui.overlay.monitor_payload import decode_monitor, encode_monitor
from app.ui.overlay.tk_backend import tk_geometry


class MonitorTests(unittest.TestCase):
    def test_round_trips_secondary_monitor_with_negative_offset(self) -> None:
        monitor = MonitorInfo("display-b", 2, -2560, 164, 2560, 1440)

        restored = decode_monitor(encode_monitor(monitor))

        self.assertEqual(restored, monitor)
        self.assertEqual(tk_geometry(restored), "2560x1440-2560+164")

    def test_rejects_invalid_child_monitor_payload(self) -> None:
        valid = json.loads(encode_monitor(MonitorInfo("display-a", 1, 0, 0, 8, 4)))
        for patch in (
            {"index": 0},
            {"width": 0},
            {"width": True},
            {"left": "0"},
            {"is_primary": 1},
            {"id": ""},
            {"extra": 1},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                decode_monitor(json.dumps(valid | patch))

    def test_rejects_zero_geometry_before_opening_tk(self) -> None:
        with self.assertRaises(ValueError):
            tk_geometry(MonitorInfo("invalid", 1, 0, 0, 0, 100))


if __name__ == "__main__":
    unittest.main()
