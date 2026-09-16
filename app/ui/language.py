"""Persist the dashboard language outside pywebview's private browser storage."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SUPPORTED_LANGUAGES = frozenset({"en", "zh"})
DEFAULT_LANGUAGE = "en"


def load_ui_language(data_dir: Path | None) -> str:
    if data_dir is None:
        return DEFAULT_LANGUAGE
    try:
        payload = json.loads(
            (Path(data_dir) / "ui-language.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError):
        return DEFAULT_LANGUAGE
    language = payload.get("language") if isinstance(payload, dict) else None
    if isinstance(language, str) and language in SUPPORTED_LANGUAGES:
        return language
    return DEFAULT_LANGUAGE


def save_ui_language(data_dir: Path | None, language: str) -> str:
    if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
        raise ValueError("Unsupported dashboard language")
    if data_dir is None:
        return language
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, prefix="ui-language-",
            suffix=".json", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump({"language": language}, handle, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, directory / "ui-language.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return language
