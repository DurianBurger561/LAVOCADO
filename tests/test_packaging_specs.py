"""User and Developer specs stay separate and exclude the wrong tree."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lavocado_packaging.spec_common import (
    MODEL_HIDDENIMPORTS,
    USER_EXCLUDES,
    developer_datas,
    developer_hiddenimports,
    required_model_datas,
    user_datas,
)
from scripts.verify_model_bundle import verify_model_bundle

ROOT = Path(__file__).resolve().parents[1]


class PackagingSpecTests(unittest.TestCase):
    def test_lab_hardware_workers_are_developer_only(self) -> None:
        hidden = developer_hiddenimports([])
        for module in (
            "developer.benchmark.capture_benchmark",
            "developer.benchmark.capture_stability",
            "developer.benchmark.diagnostic_worker",
            "developer.benchmark.jobs",
            "psutil",
        ):
            self.assertIn(module, hidden)
        self.assertIn("developer", USER_EXCLUDES)

    def test_both_editions_collect_every_pinned_model_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "lavocado_packaging.spec_common.is_expected_nudenet_model",
            return_value=True,
        ), patch(
            "lavocado_packaging.spec_common.is_expected_yolo_model",
            return_value=True,
        ), patch(
            "lavocado_packaging.spec_common.is_expected_viddexa_model",
            return_value=True,
        ), patch(
            "lavocado_packaging.spec_common.collect_data_files",
            return_value=[],
        ):
            data = user_datas(Path(temp_dir))
            developer_data = developer_datas(Path(temp_dir))

        bundled = {(Path(source).name, target) for source, target in data}
        self.assertIn(("640m.onnx", "models"), bundled)
        self.assertIn(("yolo11.pt", "models"), bundled)
        for model_id in ("viddexa_nano", "viddexa_mini"):
            for name in ("model.safetensors", "config.json", "preprocessor_config.json"):
                self.assertIn((name, f"models/{model_id}"), bundled)
        self.assertEqual(len(data), 9)  # two weights, six Viddexa files, web UI
        self.assertTrue(set(data).issubset(set(developer_data)))
        self.assertIn("developer/benchmark/ui", {target for _, target in developer_data})

    def test_missing_required_model_stops_spec_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "lavocado_packaging.spec_common.is_expected_yolo_model",
            return_value=False,
        ), self.assertRaisesRegex(SystemExit, "yolo11.pt"):
            required_model_datas(Path(temp_dir))

    def test_artifact_validator_requires_all_four_models(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            models = Path(temp_dir) / "_internal" / "models"
            models.mkdir(parents=True)
            (models / "640m.onnx").touch()
            with patch("scripts.verify_model_bundle.is_expected_nudenet_model", return_value=True), patch(
                "scripts.verify_model_bundle.is_expected_yolo_model", return_value=True
            ), patch("scripts.verify_model_bundle.is_expected_viddexa_model", return_value=True):
                verify_model_bundle(Path(temp_dir))
            with patch("scripts.verify_model_bundle.is_expected_nudenet_model", return_value=True), patch(
                "scripts.verify_model_bundle.is_expected_yolo_model", return_value=False
            ), self.assertRaisesRegex(RuntimeError, "YOLO11"):
                verify_model_bundle(Path(temp_dir))

    def test_package_matrix_downloads_all_models_before_build(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "package.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python scripts/download_models.py --model all", workflow)
        self.assertLess(
            workflow.index("python scripts/download_models.py --model all"),
            workflow.index("python -m PyInstaller"),
        )
        self.assertIn("python scripts/verify_model_bundle.py", workflow)
        self.assertIn("python scripts/verify_model_runtime.py", workflow)
        self.assertEqual(workflow.count("os: windows-latest"), 2)
        self.assertEqual(workflow.count("os: macos-latest"), 2)
        self.assertEqual(workflow.count("          - os:"), 4)
        tests_workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )
        test_matrix = tests_workflow.split("        os:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(
            test_matrix.splitlines(),
            ["          - windows-latest", "          - macos-latest"],
        )
        self.assertIn("-r requirements-context.txt", (ROOT / "requirements.txt").read_text())
        self.assertIn("-r requirements-yolo.txt", (ROOT / "requirements.txt").read_text())
        self.assertIn("ultralytics", MODEL_HIDDENIMPORTS)
        self.assertIn(
            "transformers.models.efficientnet.modeling_efficientnet",
            MODEL_HIDDENIMPORTS,
        )

    def test_project_build_helpers_do_not_shadow_pypi_packaging(self) -> None:
        output = subprocess.check_output(
            [
                sys.executable,
                "-c",
                (
                    "import packaging; "
                    "from packaging.version import parse; "
                    "print(packaging.__file__); print(parse('1.2.3'))"
                ),
            ],
            cwd=ROOT,
            text=True,
        ).splitlines()

        self.assertFalse((ROOT / "packaging").exists())
        self.assertIn(
            Path(output[0]).resolve().parent.parent.name,
            {"site-packages", "dist-packages"},
        )
        self.assertEqual(output[1], "1.2.3")

    def test_user_spec_excludes_developer_and_uses_main(self) -> None:
        text = (ROOT / "lavocado.spec").read_text(encoding="utf-8")
        self.assertIn("from lavocado_packaging.spec_common import", text)
        self.assertNotIn("from packaging.spec_common import", text)
        self.assertIn('["main.py"]', text)
        self.assertIn("USER_EXCLUDES", text)
        self.assertNotIn("developer_main.py", text)
        self.assertNotIn("lab.js", text)

    def test_developer_spec_includes_lab_and_uses_developer_main(self) -> None:
        text = (ROOT / "lavocado-developer.spec").read_text(encoding="utf-8")
        self.assertIn("from lavocado_packaging.spec_common import", text)
        self.assertNotIn("from packaging.spec_common import", text)
        self.assertIn("developer_main.py", text)
        self.assertIn("developer_datas", text)
        self.assertIn("developer_hiddenimports", text)
        self.assertNotIn("USER_EXCLUDES", text)
