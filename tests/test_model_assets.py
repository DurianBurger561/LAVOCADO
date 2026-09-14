"""Tests for portable NudeNet model discovery and validation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.vision.model_assets import (
    bundled_nudenet_model_path,
    bundled_viddexa_model_path,
    is_expected_nudenet_model,
    is_expected_viddexa_model,
    is_expected_yolo_model,
    resolve_nudenet_model_path,
    resolve_viddexa_model_path,
    resolve_yolo_model_path,
)


class ModelAssetTests(unittest.TestCase):
    def test_resolves_bundled_model_from_resource_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path = bundled_nudenet_model_path(root)
            model_path.parent.mkdir()
            model_path.touch()

            resolved = resolve_nudenet_model_path(environ={}, root=root)

        self.assertEqual(resolved, model_path)

    def test_environment_override_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "custom.onnx"
            model_path.touch()

            resolved = resolve_nudenet_model_path(
                environ={"LAVOCADO_NUDENET_MODEL": str(model_path)},
                root=Path("unused"),
            )

        self.assertEqual(resolved, model_path)

    def test_resolves_yolo_override_and_missing_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "nsfw.pt"
            model_path.touch()
            resolved = resolve_yolo_model_path(
                environ={"LAVOCADO_YOLO_MODEL": str(model_path)},
                root=Path("unused"),
            )
            missing = resolve_yolo_model_path(environ={}, root=Path(temp_dir))

        self.assertEqual(resolved, model_path)
        self.assertIsNone(missing)

    def test_viddexa_uses_bundled_resource_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = root / "models" / "viddexa_nano"
            self.assertEqual(bundled_viddexa_model_path("viddexa_nano", root), expected)
            with patch(
                "app.vision.model_assets.has_complete_viddexa_model",
                side_effect=lambda path, _model_id: path == expected,
            ):
                resolved = resolve_viddexa_model_path("viddexa_nano", root=root)
            self.assertEqual(resolved, expected)
            self.assertFalse(is_expected_viddexa_model(expected, "viddexa_nano"))

    def test_missing_model_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resolved = resolve_nudenet_model_path(
                environ={},
                root=Path(temp_dir),
            )

        self.assertIsNone(resolved)

    def test_validation_rejects_wrong_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "640m.onnx"
            model_path.write_bytes(b"not an ONNX model")

            with patch(
                "app.vision.model_assets.NUDENET_640M_SIZE",
                model_path.stat().st_size,
            ):
                self.assertFalse(is_expected_nudenet_model(model_path))
            self.assertFalse(is_expected_yolo_model(model_path))


if __name__ == "__main__":
    unittest.main()
