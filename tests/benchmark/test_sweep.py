"""Proposal/strong sweep keeps only legal pairs."""

from __future__ import annotations

import unittest
from pathlib import Path

from developer.benchmark.configs import (
    TARGET_CONTEXT_POLICY,
    ConfigSelection,
    expand_configs,
)
from developer.benchmark.dataset import BenchmarkDataset
from developer.benchmark.sweep import iter_sweep_pairs, sweep_thresholds


class SweepPairTests(unittest.TestCase):
    def test_context_policy_has_no_visual_threshold_sweep(self) -> None:
        config = expand_configs(ConfigSelection(benchmark_target=TARGET_CONTEXT_POLICY))[0]
        dataset = BenchmarkDataset("context", Path("/missing"), "now")

        with self.assertRaisesRegex(ValueError, "no visual thresholds"):
            sweep_thresholds(dataset, config)

    def test_drops_proposal_at_or_above_strong(self) -> None:
        pairs = iter_sweep_pairs((0.55, 0.60, 0.65), (0.35, 0.40, 0.45, 0.60))
        self.assertIn((0.55, 0.35), pairs)
        self.assertIn((0.55, 0.45), pairs)
        self.assertNotIn((0.55, 0.60), pairs)
        self.assertIn((0.65, 0.60), pairs)
        self.assertTrue(all(proposal is None or proposal < strong for strong, proposal in pairs))

    def test_none_proposal_keeps_strong_only_rows(self) -> None:
        pairs = iter_sweep_pairs((0.55, 0.60), (None,))
        self.assertEqual(pairs, [(0.55, None), (0.60, None)])
