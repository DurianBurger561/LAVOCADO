"""Pinned model catalog, status, and downloads never leak filesystem paths."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.vision.model_assets import resolve_nudenet_model_path
from app.vision.model_lifecycle import (
    CATALOG,
    REQUIRED_MODEL_IDS,
    ModelSpec,
    compact_model_status,
    download_huggingface,
    download_model,
    inspect_models,
    required_model_ids,
    reset_runtime_for_tests,
    start_download,
    start_download_all,
)


class ModelLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_for_tests()

    def test_all_four_release_models_are_required(self) -> None:
        self.assertEqual(
            set(REQUIRED_MODEL_IDS),
            {"nudenet_640m", "yolo11_nsfw_small", "viddexa_nano", "viddexa_mini"},
        )
        self.assertTrue(all(spec.required for spec in CATALOG))
        optional = ModelSpec("optional", "Optional", "context", "test", required=False)
        self.assertEqual(required_model_ids(CATALOG + (optional,)), REQUIRED_MODEL_IDS)

    def test_status_has_no_filesystem_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rows = inspect_models(data_dir=Path(temp_dir), root=Path(temp_dir), environ={})
        payload = json.dumps(rows)
        self.assertNotIn("/tmp", payload)
        self.assertNotIn(temp_dir, payload)
        self.assertNotIn("640m.onnx", payload)
        ids = {row["id"] for row in rows}
        self.assertEqual(
            ids,
            {"nudenet_640m", "yolo11_nsfw_small", "viddexa_nano", "viddexa_mini"},
        )
        nudenet = next(row for row in rows if row["id"] == "nudenet_640m")
        self.assertEqual(nudenet["status"], "missing")
        self.assertEqual(nudenet["fallback"], "nudenet_320n")
        self.assertTrue(nudenet["required"])
        yolo = next(row for row in rows if row["id"] == "yolo11_nsfw_small")
        self.assertTrue(yolo["downloadable"])
        self.assertTrue(yolo["required"])
        self.assertEqual(yolo["source"], "huggingface:erax-ai/EraX-NSFW-V1.0")
        for row in rows:
            self.assertTrue(row["required"])
            self.assertTrue(row["downloadable"])

    def test_resolves_user_data_dir_nudenet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            target = data_dir / "models" / "640m.onnx"
            target.parent.mkdir()
            target.write_bytes(b"weights")
            resolved = resolve_nudenet_model_path(
                environ={},
                root=Path(temp_dir) / "unused",
                data_dir=data_dir,
            )
        self.assertEqual(resolved, target)

    def test_yolo_download_uses_pinned_huggingface_file(self) -> None:
        requests: list[str] = []

        class FakeResponse:
            def read(self, _size: int = -1) -> bytes:
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *_: object) -> None:
                return None

        def opener(request: object, timeout: int = 120) -> FakeResponse:
            del timeout
            requests.append(str(getattr(request, "full_url", "")))
            return FakeResponse()

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.vision.model_lifecycle.is_expected_yolo_model",
            return_value=True,
        ):
            row = download_model(
                "yolo11_nsfw_small",
                data_dir=Path(temp_dir),
                opener=opener,
            )
        self.assertIn("erax-ai/EraX-NSFW-V1.0", requests[0])
        self.assertEqual(row["status"], "available")
        self.assertNotIn("yolo11.pt", json.dumps(row))

    def test_viddexa_download_uses_pinned_revision_and_local_bundle_path(self) -> None:
        calls: list[tuple[str, str, Path, str]] = []

        def fake_hf(
            repo_id: str,
            revision: str,
            destination: Path,
            *,
            model_id: str,
            force: bool,
        ) -> None:
            del force
            calls.append((repo_id, revision, destination, model_id))

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.vision.model_lifecycle.is_expected_viddexa_model",
            side_effect=[False, True],
        ), patch(
            "app.vision.model_lifecycle.resolve_viddexa_model_path",
            return_value=Path(temp_dir) / "models" / "viddexa_nano",
        ):
            row = download_model(
                "viddexa_nano",
                data_dir=Path(temp_dir),
                huggingface_downloader=fake_hf,
            )
            self.assertEqual(calls[0][2], Path(temp_dir) / "models" / "viddexa_nano")
        self.assertEqual(calls[0][0], "viddexa/nsfw-detection-2-nano")
        self.assertEqual(calls[0][1], "12e57200346246b37382f746e4d94d10b014f6a1")
        self.assertEqual(calls[0][3], "viddexa_nano")
        self.assertEqual(row["status"], "available")
        self.assertEqual(compact_model_status([row])["viddexa_nano"], "available")

    def test_hub_snapshot_contains_only_pinned_bundle_files(self) -> None:
        destination = Path("/build/models/viddexa_nano")
        with patch("huggingface_hub.snapshot_download") as snapshot:
            download_huggingface(
                "viddexa/nsfw-detection-2-nano",
                "12e57200346246b37382f746e4d94d10b014f6a1",
                destination,
                model_id="viddexa_nano",
            )
        self.assertEqual(snapshot.call_args.kwargs["local_dir"], destination)
        self.assertEqual(
            set(snapshot.call_args.kwargs["allow_patterns"]),
            {"model.safetensors", "config.json", "preprocessor_config.json"},
        )

    def test_incomplete_viddexa_snapshot_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.vision.model_lifecycle.is_expected_viddexa_model",
            return_value=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "pinned-file verification"):
                download_model(
                    "viddexa_nano",
                    data_dir=Path(temp_dir),
                    huggingface_downloader=lambda *_args, **_kwargs: None,
                )

    def test_download_all_skips_future_non_required_models(self) -> None:
        rows = [
            {"id": "nudenet_640m", "status": "missing", "required": True},
            {"id": "optional", "status": "missing", "required": False},
        ]
        with patch("app.vision.model_lifecycle.inspect_models", return_value=rows), patch(
            "app.vision.model_lifecycle.start_download",
            return_value={"id": "nudenet_640m", "status": "downloading"},
        ) as start:
            result = start_download_all()
        start.assert_called_once()
        self.assertEqual(result[1], rows[1])

    def test_unknown_model_raises(self) -> None:
        with self.assertRaises(ValueError):
            start_download("not-a-model")


if __name__ == "__main__":
    unittest.main()
