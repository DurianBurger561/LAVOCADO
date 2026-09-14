"""Persisted settings must validate the current schema before Protection uses them."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.settings.schema import default_vision_settings, sanitize_vision_settings
from app.settings.storage import load_vision_settings, settings_path


class SettingsStorageTests(unittest.TestCase):
    def test_unknown_or_missing_schema_version_uses_typed_defaults(self) -> None:
        with TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            path = settings_path(data_dir)
            for version in (None, 999):
                payload = {"detector": {"primary": "yolo11_nsfw_small"}}
                if version is not None:
                    payload["schema_version"] = version
                path.write_text(json.dumps(payload), encoding="utf-8")

                loaded = load_vision_settings(data_dir)

                self.assertEqual(loaded, default_vision_settings())

    def test_validation_keeps_temporal_requirement_within_window(self) -> None:
        settings = sanitize_vision_settings(
            {"temporal": {"window_size": 2, "min_fresh_hits": 3}}
        )

        self.assertEqual(settings.temporal.window_size, 2)
        self.assertEqual(settings.temporal.min_fresh_hits, 2)

    def test_invalid_boolean_values_do_not_enable_features(self) -> None:
        settings = sanitize_vision_settings(
            {"shadow": {"enabled": "false"}, "tiles": {"enabled": "false"}}
        )

        self.assertFalse(settings.shadow.enabled)
        self.assertTrue(settings.tiles.enabled)


if __name__ == "__main__":
    unittest.main()
