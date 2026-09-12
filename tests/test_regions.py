"""Tests for vision coordinate mapping and context crops."""

import unittest

import numpy as np

from app.vision.regions import expand_region, make_context_crop, map_box_to_original


class RegionTests(unittest.TestCase):
    def test_maps_xywh_box_from_model_to_original_frame(self) -> None:
        region = map_box_to_original(
            [100, 50, 200, 100],
            (360, 640, 3),
            (1080, 1920, 3),
        )

        self.assertEqual(region, (300, 150, 900, 450))

    def test_expansion_clamps_to_image_bounds(self) -> None:
        region = expand_region((0, 0, 100, 100), (200, 200, 3), 2.0)

        self.assertEqual(region, (0, 0, 150, 150))

    def test_context_crop_uses_expanded_original_pixels(self) -> None:
        original = np.zeros((1080, 1920, 3), dtype=np.uint8)

        crop_result = make_context_crop(
            original,
            [100, 50, 200, 100],
            (360, 640, 3),
            1.5,
        )

        self.assertIsNotNone(crop_result)
        assert crop_result is not None
        crop, region = crop_result
        self.assertEqual(region, (150, 75, 1050, 525))
        self.assertEqual(crop.shape, (450, 900, 3))
        self.assertTrue(crop.flags.c_contiguous)

    def test_rejects_invalid_or_outside_box(self) -> None:
        self.assertIsNone(
            map_box_to_original(
                [900, 100, 50, 50],
                (360, 640, 3),
                (1080, 1920, 3),
            )
        )
        self.assertIsNone(
            map_box_to_original(
                [10, 10, 0, 20],
                (360, 640, 3),
                (1080, 1920, 3),
            )
        )


if __name__ == "__main__":
    unittest.main()
