"""Frozen self-check validates assets and models without GUI or screenshots."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from app.self_check import perform_self_check, verify_model
from app.vision.model_manifest import ModelRole, ModelSpec, PinnedModelFile


class SelfCheckTests(unittest.TestCase):
    def test_model_asset_digest_is_required_before_loading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_path = root / "models" / "640m.onnx"
            model_path.parent.mkdir()
            model_path.write_bytes(b"pinned model")
            spec = ModelSpec(
                "nudenet_640m", "NudeNet 640m", ModelRole.PRIMARY_DETECTOR,
                "test", True, bundled_path="models/640m.onnx",
                required_files=(PinnedModelFile(
                    "640m.onnx", model_path.stat().st_size,
                    hashlib.sha256(model_path.read_bytes()).hexdigest(),
                ),),
            )
            with patch("app.vision.detectors.nudenet.NudeNetPrimaryDetector") as detector:
                detector.return_value.model_variant = "640m"
                verify_model(spec, root)
                detector.assert_called_once_with(model_path=model_path)
                model_path.write_bytes(b"pinned modeX")
                with self.assertRaisesRegex(RuntimeError, "digest"):
                    verify_model(spec, root)
                detector.assert_called_once()

    def test_self_check_reports_safe_failures_without_gui(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "app.self_check._runtime_available", return_value=True
        ), patch("app.self_check._platform_available", return_value=True), patch(
            "app.self_check.verify_model", side_effect=RuntimeError("/private/path")
        ):
            root = Path(temporary)
            web = root / "app" / "ui" / "web"
            web.mkdir(parents=True)
            for name in ("index.html", "styles.css", "i18n.js", "app.js"):
                (web / name).touch()
            report = perform_self_check(root=root)
        self.assertTrue(report["Dashboard assets"])
        self.assertTrue(report["SQLite"])
        self.assertFalse(report["NudeNet 640m"])
        self.assertNotIn("/private/path", str(report))

    def test_entrypoint_routes_self_check_before_gui(self) -> None:
        with patch("app.self_check.print_self_check", return_value=0) as check, patch(
            "main.create_platform_adapter",
            side_effect=AssertionError("GUI path must not start"),
        ):
            self.assertEqual(main.main(["--self-check"]), 0)
            check.assert_called_once_with()
