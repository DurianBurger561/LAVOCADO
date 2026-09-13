"""The prepared-image cache is scoped to one canonical capture generation."""

import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.platforms.capture.models import CaptureFrame, Rect
from app.vision.preprocessor import FramePreprocessor, TileSpec


def frame(sequence: int = 1) -> CaptureFrame:
    pixels = np.arange(6 * 8 * 3, dtype=np.uint8).reshape(6, 8, 3)
    return CaptureFrame(image=pixels, monitor_id="display-1", sequence=sequence)


class FramePreprocessorTests(unittest.TestCase):
    def test_resize_preserves_aspect_ratio_and_caches_per_generation(self) -> None:
        prepared = FramePreprocessor(frame())

        with patch("app.vision.preprocessor.cv2.resize", wraps=cv2.resize) as resize:
            first = prepared.resized_long_edge(4)
            second = prepared.resized_long_edge(4)

        self.assertIs(first, second)
        self.assertEqual(first.shape, (3, 4, 3))
        self.assertEqual(resize.call_count, 1)
        self.assertIsNot(first, FramePreprocessor(frame(2)).resized_long_edge(4))

    def test_rgb_is_contiguous_cached_and_does_not_mutate_bgr(self) -> None:
        prepared = FramePreprocessor(frame())

        rgb = prepared.rgb()

        self.assertIs(rgb, prepared.rgb())
        self.assertTrue(rgb.flags.c_contiguous)
        self.assertEqual(tuple(rgb[0, 0]), tuple(prepared.original[0, 0, ::-1]))
        self.assertEqual(tuple(prepared.original[0, 0]), (0, 1, 2))

    def test_crop_and_resized_crop_share_cached_pixels(self) -> None:
        prepared = FramePreprocessor(frame())
        rect = Rect(2, 1, 4, 3)

        self.assertIs(prepared.crop(rect), prepared.crop_xyxy((2, 1, 6, 4)))
        self.assertEqual(prepared.crop(rect).shape, (3, 4, 3))
        self.assertIs(prepared.resized_crop(rect, 2), prepared.resized_crop(rect, 2))
        self.assertEqual(prepared.resized_crop(rect, 2).shape, (2, 2, 3))
        self.assertIsNone(prepared.crop(Rect(20, 20, 1, 1)))

    def test_tiles_cover_odd_edges_and_reuse_crops(self) -> None:
        prepared = FramePreprocessor(frame())
        spec = TileSpec(2, 2)

        tiles = prepared.tiles(spec)

        self.assertIs(tiles, prepared.tiles(spec))
        self.assertEqual(len(tiles), 4)
        self.assertEqual(tiles[0].region, (0, 0, 4, 3))
        self.assertEqual(tiles[-1].region, (4, 3, 8, 6))
        self.assertIs(tiles[0].image, prepared.crop_xyxy(tiles[0].region))
        self.assertEqual(len(prepared.subtiles(tiles[0].region)), 4)

    def test_context_crop_maps_model_box_to_original(self) -> None:
        prepared = FramePreprocessor(frame())

        result = prepared.context_crop((1, 1, 2, 2), (6, 8, 3), 1.0)

        assert result is not None
        crop, region = result
        self.assertEqual(region, (1, 1, 3, 3))
        self.assertIs(crop, prepared.crop_xyxy(region))

    def test_rejects_cache_reuse_with_a_different_frame(self) -> None:
        prepared = FramePreprocessor(frame(1))

        with self.assertRaisesRegex(ValueError, "different capture frame"):
            prepared.require_frame(frame(2))


if __name__ == "__main__":
    unittest.main()
