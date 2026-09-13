"""Persist vision settings as privacy-safe JSON. Never stores pixels or URLs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

from app.settings.schema import VisionSettings, sanitize_vision_settings

SETTINGS_FILENAME = "vision_settings.json"
_LOCK = Lock()


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / SETTINGS_FILENAME


def load_vision_settings(data_dir: Path | None = None) -> VisionSettings:
    """Load sanitized settings. Missing or corrupt files become defaults."""

    if data_dir is None:
        return sanitize_vision_settings(None)
    path = settings_path(data_dir)
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return sanitize_vision_settings(None)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return sanitize_vision_settings(None)
    if not isinstance(payload, dict):
        return sanitize_vision_settings(None)
    return sanitize_vision_settings(payload)


def save_vision_settings(settings: VisionSettings, data_dir: Path) -> Path:
    """Atomically write a sanitized settings document."""

    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = settings_path(directory)
    payload = sanitize_vision_settings(settings.to_dict()).to_dict()
    temporary = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    return path


def reset_vision_settings(data_dir: Path) -> VisionSettings:
    settings = sanitize_vision_settings(None)
    save_vision_settings(settings, data_dir)
    return settings


def public_settings_view(settings: VisionSettings) -> dict[str, Any]:
    """JSON for the dashboard. Includes options and an experimental disclaimer."""

    payload = settings.to_dict()
    payload["experimental"] = True
    payload["recommended_locked"] = True
    payload["disclaimer"] = (
        "Experimental Defaults. Reset to Recommended stays locked until "
        "screen-domain benchmark selects values."
    )
    payload["options"] = {
        "primary": ["nudenet_640m", "yolo11_nsfw_small"],
        "context": ["off", "viddexa_nano", "viddexa_mini"],
        "preset": ["low_cpu", "balanced", "high_recall"],
        "full_input_size": [640, 960, 1280],
        "tile_input_size": [640, 960],
        "grid": ["2x2", "3x3"],
        "overlap": [0, 10, 15, 20, 25],
        "crop_expansion": [1.25, 1.5, 1.75, 2.0, 2.5],
        "checks_per_scan": [1, 2],
        "max_skip": [1, 2, 3, 4, 5, 6, 7, 8],
        "proposal_margin": [0.05, 0.10, 0.15, 0.20],
        "change_sensitivity": [0.005, 0.01, 0.02, 0.05],
        "min_fresh_hits": [1, 2, 3],
        "evidence_threshold": [1.5, 2.0, 2.5, 3.0, 3.5],
        "decay": [0.3, 0.5, 0.7],
    }
    return payload
