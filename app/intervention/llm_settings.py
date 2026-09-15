"""Local storage for the optional meditation LLM connection."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any


LLM_SETTINGS_FILENAME = "llm_settings.json"
_LOCK = Lock()


SUPPORTED_CONVERSATION_LANGUAGES = frozenset({"zh", "en"})


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """Connection settings; conversation content is never stored here."""

    api_key: str = ""
    endpoint: str = ""
    model: str = ""
    enabled: bool = True
    # Empty means "speak whatever the dashboard speaks".
    language: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / LLM_SETTINGS_FILENAME


def load_llm_settings(data_dir: Path | None = None) -> LLMSettings:
    if data_dir is None:
        return LLMSettings()
    try:
        with settings_path(data_dir).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
        return LLMSettings()
    return sanitize_llm_settings(payload)


def sanitize_llm_settings(payload: object) -> LLMSettings:
    if not isinstance(payload, dict):
        return LLMSettings()
    return LLMSettings(
        api_key=_text(payload.get("api_key"), 4096),
        endpoint=_text(payload.get("endpoint"), 500),
        model=_text(payload.get("model"), 120),
        enabled=payload.get("enabled") if isinstance(payload.get("enabled"), bool) else True,
        language=_language(payload.get("language")),
    )


def save_llm_settings(settings: LLMSettings, data_dir: Path) -> Path:
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = settings_path(directory)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = sanitize_llm_settings(settings.to_dict()).to_dict()
    with _LOCK:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path


def _text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _language(value: object) -> str:
    """Keep only a language the companion can actually speak, or nothing."""

    language = _text(value, 8).casefold()
    return language if language in SUPPORTED_CONVERSATION_LANGUAGES else ""
