"""Dashboard language persistence and translation resource contracts."""

import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from app.ui.api import DashboardAPI
from app.ui.language import load_ui_language, save_ui_language

WEB_ROOT = Path(__file__).resolve().parents[1] / "app" / "ui" / "web"
TRANSLATION_PATTERN = re.compile(r"const ZH = Object\.freeze\((\{.*?\})\);", re.DOTALL)
HAN = re.compile(r"[\u4e00-\u9fff]")


class _StaticText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.values.append(" ".join(data.split()))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"aria-label", "placeholder", "title"} and value:
                self.values.append(" ".join(value.split()))


class UILanguageTests(unittest.TestCase):
    def test_language_round_trips_through_api_and_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = DashboardAPI(object(), object(), data_dir=root)
            self.assertEqual(first.get_ui_language(), {"ok": True, "language": "en"})
            self.assertEqual(first.set_ui_language("zh"), {"ok": True, "language": "zh"})
            self.assertEqual(load_ui_language(root), "zh")
            second = DashboardAPI(object(), object(), data_dir=root)
            self.assertEqual(second.get_ui_language(), {"ok": True, "language": "zh"})
            self.assertEqual(second.set_ui_language("en"), {"ok": True, "language": "en"})
            self.assertEqual(load_ui_language(root), "en")

    def test_bad_language_does_not_change_saved_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            api = DashboardAPI(object(), object(), data_dir=root)
            api.set_ui_language("zh")
            for invalid in ("fr", "ZH", "", None, 1):
                with self.subTest(invalid=invalid):
                    self.assertFalse(api.set_ui_language(invalid)["ok"])
                    self.assertEqual(api.get_ui_language()["language"], "zh")
            self.assertEqual(load_ui_language(root), "zh")

    def test_corrupt_language_file_uses_english_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            language_file = root / "ui-language.json"
            for contents in ("not json", "null", '{"language": "fr"}'):
                with self.subTest(contents=contents):
                    language_file.write_text(contents, encoding="utf-8")
                    self.assertEqual(load_ui_language(root), "en")
            self.assertEqual(save_ui_language(None, "zh"), "zh")
            self.assertEqual(load_ui_language(None), "en")

    def test_static_english_content_has_chinese_translation(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        translations = (WEB_ROOT / "i18n.js").read_text(encoding="utf-8")
        match = TRANSLATION_PATTERN.search(translations)
        self.assertIsNotNone(match)
        dictionary = json.loads(match.group(1))
        parser = _StaticText()
        parser.feed(html)
        technical = {
            "LAVOCADO", "NudeNet", "NudeNet 640m", "YOLO11 NSFW Small",
            "Viddexa Nano", "Viddexa Mini", "MSS", "ROI",
            "chrome.exe", "org.example.viewer", "example.com",
        }
        missing = [value for value in parser.values if re.search(r"[A-Za-z]", value) and value not in technical and value not in dictionary]
        self.assertEqual(missing, [])
        dynamic_literals = re.findall(r'\bt\("([^"]+)"', script)
        dynamic_literals += re.findall(r'\btext\("[^"]+",\s*"([^"]+)"', script)
        self.assertEqual(
            [value for value in dynamic_literals if re.search(r"[A-Za-z]", value) and value not in dictionary],
            [],
        )
        self.assertFalse(HAN.search(html))
        self.assertFalse(HAN.search(script))
        technical_terms = re.compile(
            r"\b(?:LAVOCADO|NudeNet|YOLO11|YOLO|NSFW|Viddexa|Nano|Mini|Small|CPU|ROI|HTTPS|URL|MSS|\d+[a-z])\b"
        )
        for source, translation in dictionary.items():
            with self.subTest(source=source):
                visible = re.sub(r"\{\w+\}", "", translation)
                visible = technical_terms.sub("", visible)
                self.assertFalse(re.search(r"[A-Za-z]", visible))
        self.assertIn("window.LavocadoI18n = LavocadoI18n", translations)


if __name__ == "__main__":
    unittest.main()
