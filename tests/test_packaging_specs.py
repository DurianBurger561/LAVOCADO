"""The release spec bundles every required model and dashboard asset."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lavocado_packaging.spec_common import (
    MODEL_HIDDENIMPORTS,
    MODEL_METADATA,
    model_dependency_binaries,
    required_model_datas,
    user_datas,
)
from scripts.verify_model_bundle import verify_model_bundle

ROOT = Path(__file__).resolve().parents[1]


class PackagingSpecTests(unittest.TestCase):
    def test_release_collects_every_pinned_model_file(self) -> None:
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
        ), patch(
            "lavocado_packaging.spec_common.copy_metadata",
            return_value=[],
        ):
            data = user_datas(Path(temp_dir))

        bundled = {(Path(source).name, target) for source, target in data}
        self.assertIn(("640m.onnx", "models"), bundled)
        self.assertIn(("yolo11.pt", "models"), bundled)
        for model_id in ("viddexa_nano", "viddexa_mini"):
            for name in ("model.safetensors", "config.json", "preprocessor_config.json"):
                self.assertIn((name, f"models/{model_id}"), bundled)
        self.assertEqual(len(data), 9)  # two weights, six Viddexa files, web UI

    def test_missing_required_model_stops_spec_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "lavocado_packaging.spec_common.is_expected_nudenet_model",
            return_value=True,
        ), patch(
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
        self.assertIn("run: '\"${{ matrix.executable }}\" --self-check'", workflow)
        self.assertEqual(workflow.count("            executable:"), 2)
        self.assertEqual(workflow.count("os: windows-latest"), 1)
        self.assertEqual(workflow.count("os: macos-latest"), 1)
        self.assertEqual(workflow.count("          - os:"), 2)
        tests_workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )
        test_matrix = tests_workflow.split("        os:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(
            test_matrix.splitlines(),
            ["          - windows-latest", "          - macos-latest"],
        )
        runtime_requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for dependency in (
            "huggingface_hub>=0.34,<1",
            "transformers>=4.56.1,<5",
            "torch>=2.4,<3",
            "ultralytics>=8.3,<9",
        ):
            self.assertIn(dependency, runtime_requirements)
        self.assertFalse((ROOT / "requirements-context.txt").exists())
        self.assertFalse((ROOT / "requirements-yolo.txt").exists())
        self.assertIn("ultralytics", MODEL_HIDDENIMPORTS)
        self.assertIn(
            "transformers.models.efficientnet.modeling_efficientnet",
            MODEL_HIDDENIMPORTS,
        )
        self.assertIn("transformers.pipelines", MODEL_HIDDENIMPORTS)
        self.assertIn("torch", MODEL_METADATA)
        self.assertIn("transformers", MODEL_METADATA)

    def test_release_bundles_transformers_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "lavocado_packaging.spec_common.required_model_datas",
            return_value=[],
        ), patch(
            "lavocado_packaging.spec_common.collect_data_files",
            return_value=[],
        ), patch(
            "lavocado_packaging.spec_common.copy_metadata",
            side_effect=lambda name: [(f"/{name}.dist-info", f"{name}.dist-info")],
        ) as metadata:
            user_data = user_datas(Path(temp_dir))

        self.assertEqual(metadata.call_count, len(MODEL_METADATA))
        for distribution in MODEL_METADATA:
            item = (f"/{distribution}.dist-info", f"{distribution}.dist-info")
            self.assertIn(item, user_data)

    def test_torchvision_dynamic_ops_enter_release(self) -> None:
        with patch(
            "lavocado_packaging.spec_common.collect_dynamic_libs",
            return_value=[("/wheel/torchvision/_C_stable.so", "torchvision")],
        ) as collect:
            binaries = model_dependency_binaries()

        self.assertEqual(binaries, [("/wheel/torchvision/_C_stable.so", "torchvision")])
        self.assertEqual(collect.call_args.args, ("torchvision",))
        self.assertIn("*.so", collect.call_args.kwargs["search_patterns"])
        self.assertIn("*.pyd", collect.call_args.kwargs["search_patterns"])
        source = (ROOT / "lavocado.spec").read_text(encoding="utf-8")
        self.assertIn("binaries=model_dependency_binaries()", source)

        with patch(
            "lavocado_packaging.spec_common.collect_dynamic_libs",
            return_value=[],
        ), self.assertRaisesRegex(SystemExit, "torchvision native ops"):
            model_dependency_binaries()

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

    def test_release_spec_uses_main(self) -> None:
        text = (ROOT / "lavocado.spec").read_text(encoding="utf-8")
        self.assertIn("from lavocado_packaging.spec_common import", text)
        self.assertNotIn("from packaging.spec_common import", text)
        self.assertIn('["main.py"]', text)
