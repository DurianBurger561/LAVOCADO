"""Dataset create/open/import/annotation tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from developer.benchmark.dataset import (
    DatasetError,
    create_dataset,
    import_paths,
    open_dataset,
    resolve_dataset_path,
    save_dataset,
    update_sample,
)
try:
    from benchmark.helpers import write_png
except ImportError:
    from tests.benchmark.helpers import write_png


class DatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_open_save_load(self) -> None:
        created = create_dataset(self.root, "desktop_v1")
        self.assertTrue((created.root / "dataset.json").is_file())
        loaded = open_dataset(created.root)
        self.assertEqual(loaded.name, "desktop_v1")
        loaded.name = "desktop_v1"
        save_dataset(loaded)
        again = open_dataset(loaded.document_path)
        self.assertEqual(again.schema_version, 1)

    def test_open_accepts_json_file_or_folder_outside_data_dir(self) -> None:
        created = create_dataset(self.root, "portable")
        outside = self.root / "elsewhere" / "my_set"
        outside.mkdir(parents=True)
        document = outside / "dataset.json"
        document.write_text(created.document_path.read_text(encoding="utf-8"), encoding="utf-8")
        from_file = open_dataset(document)
        from_folder = open_dataset(outside)
        self.assertEqual(from_file.root, outside.resolve())
        self.assertEqual(from_folder.root, outside.resolve())
        self.assertEqual(resolve_dataset_path(outside), document.resolve())
        with self.assertRaises(DatasetError):
            open_dataset(self.root / "missing")
        not_json = self.root / "notes.txt"
        not_json.write_text("nope", encoding="utf-8")
        with self.assertRaises(DatasetError):
            resolve_dataset_path(not_json)

    def test_import_reference_and_copy(self) -> None:
        dataset = create_dataset(self.root, "import_test")
        first = write_png(self.root / "src" / "a.png", (10, 20, 30))
        second = write_png(self.root / "src" / "b.jpg".replace(".jpg", ".png"), (40, 50, 60))
        result = import_paths(dataset, [first.parent], mode="reference")
        self.assertEqual(result["added"], 2)
        self.assertTrue(Path(dataset.samples[0].path).is_absolute())
        copied = create_dataset(self.root, "copy_test")
        copied_result = import_paths(copied, [first], mode="copy")
        self.assertEqual(copied_result["added"], 1)
        self.assertTrue(copied.resolve_path(copied.samples[0]).is_file())
        self.assertTrue(str(copied.samples[0].path).startswith("images/"))

    def test_block_allow_unlabelled_excluded_and_tags(self) -> None:
        dataset = create_dataset(self.root, "labels")
        image = write_png(self.root / "one.png")
        import_paths(dataset, [image], mode="reference")
        sample_id = dataset.samples[0].id
        labelled = update_sample(
            dataset,
            sample_id,
            expected="block",
            tags=["explicit", "small_target"],
        )
        self.assertEqual(labelled.expected, "block")
        self.assertIn("explicit", labelled.tags)
        allowed = update_sample(
            dataset,
            sample_id,
            expected="allow",
            tags=["non_pornographic_purpose", "medical"],
        )
        self.assertEqual(allowed.expected, "allow")
        unlabelled = update_sample(dataset, sample_id, expected=None)
        self.assertIsNone(unlabelled.expected)
        excluded = update_sample(dataset, sample_id, excluded=True)
        self.assertTrue(excluded.excluded)

    def test_unknown_ground_truth_is_rejected(self) -> None:
        dataset = create_dataset(self.root, "unknown")
        image = write_png(self.root / "one.png")
        import_paths(dataset, [image], mode="reference")
        with self.assertRaises(DatasetError):
            update_sample(dataset, dataset.samples[0].id, expected="unknown")

    def test_missing_invalid_and_duplicate_images(self) -> None:
        dataset = create_dataset(self.root, "quality")
        valid = write_png(self.root / "ok.png")
        missing = self.root / "missing.png"
        invalid = self.root / "notes.txt"
        invalid.write_text("not an image", encoding="utf-8")
        first = import_paths(dataset, [valid, missing, invalid], mode="reference")
        self.assertEqual(first["added"], 1)
        self.assertGreaterEqual(first["skipped_invalid"], 1)
        duplicate = import_paths(dataset, [valid], mode="reference")
        self.assertEqual(duplicate["added"], 0)
        self.assertEqual(duplicate["skipped_duplicate"], 1)
