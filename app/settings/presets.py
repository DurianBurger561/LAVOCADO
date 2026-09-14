"""Named starting points. None of these are validated Recommended values."""

from __future__ import annotations

from app.settings.schema import (
    VisionSettings,
    merge_vision_settings,
    sanitize_vision_settings,
)

PRESET_LABELS = {
    "low_cpu": "Low CPU",
    "balanced": "Balanced",
    "high_recall": "High Recall",
}


def apply_preset(name: str, current: VisionSettings | None = None) -> VisionSettings:
    """Map a preset name onto a sanitized settings object."""

    base = current or sanitize_vision_settings(None)
    presets: dict[str, dict] = {
        "low_cpu": {
            "preset": "low_cpu",
            "detector": {"full_input_size": 640, "tile_input_size": 640},
            "context": {"model": "off"},
            "tiles": {"enabled": True, "rows": 2, "columns": 2, "checks_per_scan": 1},
            "scan": {
                "normal_interval_ms": 1000,
                "candidate_interval_ms": 250,
                "adaptive": True,
                "vision_budget_ms": 150,
            },
        },
        "balanced": {
            "preset": "balanced",
            "detector": {"full_input_size": 640, "tile_input_size": 640},
            "context": {"model": "viddexa_mini"},
            "tiles": {
                "enabled": True,
                "rows": 2,
                "columns": 2,
                "overlap": 0.15,
                "checks_per_scan": 1,
            },
            "scan": {
                "normal_interval_ms": 750,
                "candidate_interval_ms": 150,
                "adaptive": True,
                "vision_budget_ms": 250,
            },
        },
        "high_recall": {
            "preset": "high_recall",
            "detector": {"full_input_size": 640, "tile_input_size": 640},
            "context": {"model": "viddexa_mini"},
            "tiles": {
                "enabled": True,
                "rows": 2,
                "columns": 2,
                "overlap": 0.20,
                "checks_per_scan": 2,
                "max_skip": 2,
            },
            "scan": {
                "normal_interval_ms": 500,
                "candidate_interval_ms": 100,
                "adaptive": True,
                "vision_budget_ms": 400,
            },
        },
    }
    patch = presets.get(name, presets["balanced"])
    return merge_vision_settings(base, patch)
