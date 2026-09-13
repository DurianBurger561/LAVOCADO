"""Annotation filters and keyboard-oriented mark helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from developer.benchmark.annotations import filter_samples, mark_allow, mark_block, toggle_exclude
from developer.benchmark.dataset import create_dataset, import_paths
try:
    from benchmark.helpers import write_png
except ImportError:
    from tests.benchmark.helpers import write_png


class AnnotationTests(unittest.TestCase):
    def test_filters_and_toggles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = create_dataset(root, "ann")
            import_paths(
                dataset,
                [
                    write_png(root / "a.png", (1, 2, 3)),
                    write_png(root / "b.png", (4, 5, 6)),
                ],
                mode="reference",
            )
            first, second = dataset.samples
            mark_block(dataset, first.id)
            mark_allow(dataset, second.id)
            toggle_exclude(dataset, second.id)
            self.assertEqual(len(filter_samples(dataset, status="block")), 1)
            self.assertEqual(len(filter_samples(dataset, status="allow")), 1)
            self.assertEqual(len(filter_samples(dataset, status="excluded")), 1)
            self.assertEqual(len(filter_samples(dataset, status="unlabelled")), 0)
