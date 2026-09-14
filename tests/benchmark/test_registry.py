"""UI and CLI share one Benchmark Lab category/runner registry."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from developer.benchmark.cli import main
from developer.benchmark.configs import ConfigSelection, expand_configs
from developer.benchmark.contracts import BenchmarkRequest
from developer.benchmark.dataset import create_dataset
from developer.benchmark.registry import BenchmarkRegistry


class RegistryTests(unittest.TestCase):
    def test_categories_cover_every_dataset_target_and_tool_page(self) -> None:
        categories = BenchmarkRegistry().categories()
        self.assertEqual(
            [entry["id"] for entry in categories],
            [
                "capture", "preprocessing", "detector_only", "region_ranking",
                "vision_pipeline", "context_policy", "full_protection_pipeline",
            ],
        )
        self.assertEqual(categories[3]["tool_mode"], "ranker_signal")

    def test_registry_starts_real_context_policy_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dataset = create_dataset(Path(temporary), "registry")
            configs = expand_configs(ConfigSelection(benchmark_target="context_policy"))
            runner = BenchmarkRegistry().runner(BenchmarkRequest(dataset, tuple(configs)))
            result = runner.start()

        self.assertFalse(result.cancelled)
        self.assertEqual(result.rows, [])

    def test_cli_lists_same_registry_categories(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--list"])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), BenchmarkRegistry().categories())


if __name__ == "__main__":
    unittest.main()
