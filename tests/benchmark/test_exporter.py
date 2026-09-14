"""JSON/CSV export omits source images."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from developer.benchmark.exporter import export_csv, export_json
from developer.benchmark.results import BenchmarkResult


class ExporterTests(unittest.TestCase):
    def test_json_and_csv_do_not_embed_images(self) -> None:
        run = BenchmarkResult(
            id="run1",
            created_at="2026-01-01T00:00:00+00:00",
            dataset_name="desktop",
            dataset_hash="abc",
            engine_version=1,
            product_version="LAVOCADO Developer",
            configs=[{"id": "c1", "detector": "nudenet_640m"}],
            rows=[
                {
                    "sample_id": "000001",
                    "config_id": "c1",
                    "expected": "block",
                    "predicted": "block",
                    "outcome": "tp",
                    "correct": True,
                    "total_ms": 12.0,
                    "tags": ["explicit"],
                    "decision_summary": {"label": "FEMALE_BREAST_EXPOSED", "confidence": 0.9, "source": "primary"},
                    "detector_summary": {"best_label": "FEMALE_BREAST_EXPOSED", "best_confidence": 0.9},
                }
            ],
            summaries={"c1": {"recall": 1.0}},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = export_json(run, Path(temp_dir) / "out.json")
            csv_path = export_csv(run, Path(temp_dir) / "out.csv")
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            dumped = json.dumps(payload)
            self.assertIn("decision_trace", dumped)
            self.assertNotIn("data:image", dumped)
            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertIn("000001", csv_text)
            self.assertNotIn("data:image", csv_text)
