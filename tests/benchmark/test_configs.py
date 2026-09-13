"""Legal configuration expansion."""

from __future__ import annotations

import unittest

from developer.benchmark.configs import (
    TILE_FULL_ONLY,
    ConfigSelection,
    expand_configs,
)


class ConfigExpansionTests(unittest.TestCase):
    def test_full_only_ignores_overlap_and_tile_input(self) -> None:
        configs = expand_configs(
            ConfigSelection(
                detectors=("nudenet_640m",),
                context_models=("off",),
                full_input_sizes=(640, 960),
                tile_modes=(TILE_FULL_ONLY,),
                overlaps=(0.10, 0.15),
                tile_input_sizes=(640, 960),
            )
        )
        self.assertEqual(len(configs), 1)
        self.assertIsNone(configs[0].tile_rows)
        self.assertEqual(configs[0].tile_overlap, 0.0)

    def test_nudenet_filters_unsupported_input_size(self) -> None:
        configs = expand_configs(
            ConfigSelection(
                detectors=("nudenet_640m",),
                context_models=("off",),
                full_input_sizes=(640, 960, 1280),
                tile_modes=(TILE_FULL_ONLY,),
            )
        )
        self.assertEqual({item.full_input_size for item in configs}, {640})

    def test_context_off_does_not_set_viddexa(self) -> None:
        configs = expand_configs(
            ConfigSelection(
                detectors=("yolo11_nsfw_small",),
                context_models=("off",),
                full_input_sizes=(640,),
                tile_modes=(TILE_FULL_ONLY,),
            )
        )
        self.assertEqual(configs[0].context_model, None)

    def test_grid_keeps_overlap_combinations(self) -> None:
        configs = expand_configs(
            ConfigSelection(
                detectors=("yolo11_nsfw_small",),
                context_models=("off",),
                full_input_sizes=(640,),
                tile_modes=("2x2",),
                overlaps=(0.0, 0.10),
                tile_input_sizes=(640,),
            )
        )
        self.assertEqual(len(configs), 2)
        self.assertEqual({item.tile_rows for item in configs}, {2})
