"""Tests for native-metadata and software-diff scan scheduling."""

import unittest

import numpy as np

from app.platforms.capture import Rect
from app.vision.capture import CapturedFrame
from app.vision.change_scheduler import ChangeScheduler


def frame(
    value: int,
    *,
    changed_regions: tuple[Rect, ...] | None = None,
) -> CapturedFrame:
    image = np.full((8, 12, 3), value, dtype=np.uint8)
    return CapturedFrame(
        original_frame=image,
        model_frame=image,
        changed_regions=changed_regions,
    )


class ChangeSchedulerTests(unittest.TestCase):
    def test_policy_skip_does_not_scan(self) -> None:
        scheduler = ChangeScheduler()

        decision = scheduler.should_scan(frame(0), 1, vision_allowed=False)

        self.assertFalse(decision.scan)
        self.assertEqual(decision.source, "policy_skip")

    def test_first_frame_is_always_scanned(self) -> None:
        scheduler = ChangeScheduler()

        decision = scheduler.should_scan(frame(0), 1)

        self.assertTrue(decision.scan)
        self.assertEqual(decision.source, "initial")

    def test_software_change_map_detects_changed_pixels(self) -> None:
        scheduler = ChangeScheduler(change_ratio_threshold=0.1)
        scheduler.should_scan(frame(0), 1)

        decision = scheduler.should_scan(frame(255), 1)

        self.assertTrue(decision.scan)
        self.assertEqual(decision.source, "software")
        self.assertEqual(decision.change_ratio, 1.0)

    def test_native_metadata_takes_priority_when_available(self) -> None:
        scheduler = ChangeScheduler()
        scheduler.should_scan(frame(0), 1)

        decision = scheduler.should_scan(
            frame(0, changed_regions=(Rect(0, 0, 3, 4),)),
            1,
        )

        self.assertTrue(decision.scan)
        self.assertEqual(decision.source, "native")
        self.assertEqual(decision.change_ratio, 0.125)

    def test_static_screen_gets_a_periodic_full_scan(self) -> None:
        scheduler = ChangeScheduler(periodic_scan_interval=2)
        scheduler.should_scan(frame(0), 1)

        skipped = scheduler.should_scan(frame(0), 1)
        periodic = scheduler.should_scan(frame(0), 1)

        self.assertFalse(skipped.scan)
        self.assertTrue(periodic.scan)
        self.assertEqual(periodic.source, "periodic")

    def test_candidate_forces_temporal_followup_frames(self) -> None:
        scheduler = ChangeScheduler(candidate_followup_checks=2)
        scheduler.should_scan(frame(0), 1)
        scheduler.record_candidate(1, True)

        first = scheduler.should_scan(frame(0), 1)
        second = scheduler.should_scan(frame(0), 1)

        self.assertTrue(first.scan)
        self.assertTrue(second.scan)
        self.assertEqual(first.source, "candidate_followup")
        self.assertEqual(second.source, "candidate_followup")

    def test_monitor_schedules_are_independent_and_resettable(self) -> None:
        scheduler = ChangeScheduler()

        self.assertTrue(scheduler.should_scan(frame(0), 1).scan)
        self.assertTrue(scheduler.should_scan(frame(0), 2).scan)
        self.assertFalse(scheduler.should_scan(frame(0), 1).scan)
        scheduler.reset()
        self.assertTrue(scheduler.should_scan(frame(0), 1).scan)

    def test_only_a_bounded_grayscale_map_is_retained(self) -> None:
        scheduler = ChangeScheduler(map_max_edge=4)
        scheduler.should_scan(frame(0), 1)

        retained = scheduler._schedules[1].previous_gray

        self.assertEqual(retained.shape, (4, 4))
        self.assertEqual(retained.dtype, np.uint8)
        self.assertEqual(retained.nbytes, 16)


if __name__ == "__main__":
    unittest.main()
