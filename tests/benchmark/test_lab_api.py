"""Benchmark Lab API methods used by the Developer dashboard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from developer.benchmark.ui.api import DeveloperDashboardAPI

try:
    from benchmark.helpers import write_png
except ImportError:
    from tests.benchmark.helpers import write_png


class FakeController:
    status = type("S", (), {"value": "Stopped"})()
    last_exit_code = None

    def close(self) -> None:
        return None


class FakeRecorder:
    def recent(self, limit: int):
        return []

    def count(self) -> int:
        return 0

    def close(self) -> None:
        return None


class LabAPITests(unittest.TestCase):
    def test_tool_start_checks_protection_and_builds_worker_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            api = DeveloperDashboardAPI(
                FakeController(), FakeRecorder(), FakeController(), data_dir=Path(temp_dir)
            )
            denied = api.lab_start_tool("capture", {"backend": "both"})
            self.assertFalse(denied["ok"])
            with (
                patch.object(api, "get_status", return_value={"ok": True, "can_start": True}),
                patch("developer.benchmark.ui.api.LabProcessJob") as job_class,
            ):
                job_class.return_value.id = "job-id"
                started = api.lab_start_tool("capture", {"backend": "both", "frames": 20})
            self.assertTrue(started["ok"])
            self.assertEqual(started["job_id"], "job-id")
            self.assertEqual(job_class.call_args.args[0], "capture")
            self.assertIn("--frames", job_class.call_args.args[1])

    def test_preprocessor_tool_rejects_oversized_synthetic_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            api = DeveloperDashboardAPI(
                FakeController(), FakeRecorder(), FakeController(), data_dir=Path(temp_dir)
            )
            with patch.object(api, "get_status", return_value={"ok": True, "can_start": True}):
                result = api.lab_start_tool(
                    "diagnostic",
                    {"mode": "preprocessor", "width": 8192, "height": 8192},
                )
            self.assertFalse(result["ok"])
            self.assertIn("16 megapixels", result["message"])

    def test_create_import_annotate_and_expand(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            api = DeveloperDashboardAPI(
                FakeController(),
                FakeRecorder(),
                FakeController(),
                data_dir=root,
            )
            created = api.lab_create_dataset("api_set")
            self.assertTrue(created["ok"])
            image = write_png(root / "shot.png")
            imported = api.lab_import_images([str(image)], "copy")
            self.assertEqual(imported["import"]["added"], 1)
            sample_id = imported["dataset"]["samples"][0]["id"]
            annotated = api.lab_annotate(
                sample_id,
                "allow",
                False,
                ["non_pornographic_purpose", "education"],
            )
            self.assertEqual(annotated["sample"]["expected"], "allow")
            visual = api.lab_annotate(sample_id, "allow", False, [], "violation")
            self.assertEqual(visual["sample"]["expected_visual"], "violation")
            configs = api.lab_expand_configs(
                {
                    "benchmark_target": "full_protection_pipeline",
                    "detectors": ["nudenet_640m"],
                    "context_models": ["off"],
                    "tile_modes": ["full_only"],
                    "threshold_profile": "balanced",
                    "crop_expansion": 1.5,
                    "proposal_margin": 0.05,
                }
            )
            self.assertGreaterEqual(configs["count"], 1)
            self.assertEqual(configs["configs"][0]["threshold_profile"], "balanced")
            self.assertIn("proposal_margins", configs["options"])
            edition = api.get_build_edition()
            self.assertEqual(edition["edition"], "developer")

    def test_open_dataset_from_json_or_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            api = DeveloperDashboardAPI(
                FakeController(),
                FakeRecorder(),
                FakeController(),
                data_dir=root,
            )
            created = api.lab_create_dataset("listed")
            self.assertTrue(created["ok"])
            outside = root / "other" / "copied"
            outside.mkdir(parents=True)
            document = outside / "dataset.json"
            document.write_text(
                (root / "benchmark_data" / "listed" / "dataset.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            from_file = api.lab_open_dataset(str(document))
            self.assertTrue(from_file["ok"])
            self.assertEqual(from_file["dataset"]["path"], str(outside.resolve()))
            from_folder = api.lab_open_dataset_folder(str(outside))
            self.assertTrue(from_folder["ok"])
            cancelled = api.lab_open_dataset(None)
            self.assertFalse(cancelled["ok"])
