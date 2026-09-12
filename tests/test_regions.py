"""Tests for vision coordinate mapping and context crops."""

import unittest

import numpy as np

from app.vision.regions import (
    crop_region,
    expand_region,
    make_context_crop,
    map_box_to_original,
    tile_regions,
)


class RegionTests(unittest.TestCase):
    def test_two_by_two_tiles_cover_odd_sized_image(self) -> None:
        regions = tile_regions((5, 7, 3), rows=2, columns=2)

        self.assertEqual(
            regions,
            (
                (0, 0, 3, 2),
                (3, 0, 7, 2),
                (0, 2, 3, 5),
                (3, 2, 7, 5),
            ),
        )
        self.assertEqual(sum((r - l) * (b - t) for l, t, r, b in regions), 35)

    def test_crop_region_returns_requested_pixels(self) -> None:
        image = np.arange(4 * 4 * 3, dtype=np.uint8).reshape((4, 4, 3))

        crop = crop_region(image, (2, 0, 4, 2))

        self.assertIsNotNone(crop)
        assert crop is not None
        np.testing.assert_array_equal(crop, image[0:2, 2:4])
        self.assertTrue(crop.flags.c_contiguous)

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
