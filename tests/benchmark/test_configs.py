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

    def test_threshold_profile_and_algorithm_settings_use_product_schema(self) -> None:
        configs = expand_configs(
            ConfigSelection(
                detectors=("nudenet_640m",),
                context_models=("off",),
                full_input_sizes=(640,),
                tile_modes=(TILE_FULL_ONLY,),
                threshold_profile="high_recall",
                settings={
                    "recheck": {"crop_expansion": 2.0, "proposal_margin": 0.15},
                    "temporal": {"confirmation": "evidence", "min_fresh_hits": 1},
                    "tiles": {"max_skip": 2, "checks_per_scan": 2},
                },
            )
        )
        settings = configs[0].vision_settings()
        self.assertEqual(configs[0].threshold_profile, "high_recall")
        self.assertEqual(settings.preset, "high_recall")
        self.assertAlmostEqual(settings.recheck.crop_expansion, 2.0)
        self.assertAlmostEqual(settings.recheck.proposal_margin, 0.15)
        self.assertEqual(settings.temporal.confirmation, "evidence")
        self.assertEqual(settings.tiles.max_skip, 2)
        self.assertEqual(settings.tiles.checks_per_scan, 2)

    def test_payload_maps_algorithm_fields_onto_settings_schema(self) -> None:
        from developer.benchmark.configs import selection_from_payload

        selection = selection_from_payload(
            {
                "threshold_profile": "balanced",
                "crop_expansion": 1.5,
                "proposal_margin": 0.05,
                "tile_ranking": False,
                "confirmation": "both",
                "window_size": 2,
            }
        )
        self.assertEqual(selection.threshold_profile, "balanced")
        self.assertAlmostEqual(selection.settings["recheck"]["crop_expansion"], 1.5)
        self.assertEqual(selection.settings["temporal"]["confirmation"], "both")
        self.assertFalse(selection.settings["context"]["tile_ranking"])
