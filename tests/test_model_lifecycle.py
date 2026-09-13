"""Pinned model catalog, status, and downloads never leak filesystem paths."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.vision.model_assets import resolve_nudenet_model_path
from app.vision.model_lifecycle import (
    compact_model_status,
    download_model,
    inspect_models,
    reset_runtime_for_tests,
    start_download,
)


class ModelLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime_for_tests()

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

    def test_viddexa_download_uses_pinned_revision(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_hf(repo_id: str, revision: str) -> None:
            calls.append((repo_id, revision))

        with patch(
            "app.vision.model_lifecycle._huggingface_cached",
            return_value=True,
        ):
            row = download_model(
                "viddexa_nano",
                huggingface_downloader=fake_hf,
            )
        self.assertEqual(calls[0][0], "viddexa/nsfw-detection-2-nano")
        self.assertEqual(row["status"], "available")
        self.assertEqual(compact_model_status([row])["viddexa_nano"], "available")

    def test_unknown_model_raises(self) -> None:
        with self.assertRaises(ValueError):
            start_download("not-a-model")


if __name__ == "__main__":
    unittest.main()
