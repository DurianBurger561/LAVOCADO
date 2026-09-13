"""Privacy-safe Vision settings snapshot. No viewing-intent modes."""

from __future__ import annotations

from typing import Any

from app import config


def vision_settings_snapshot() -> dict[str, Any]:
    """Return the Vision Settings group, never medical/art/education modes."""

    yolo_enabled = bool(config.YOLO_ENABLED)
    tile_ranking = bool(config.RESCUE_ENABLED and config.CONTEXT_MODEL_ENABLED)
    return {
        "primary_detector": "nudenet+yolo11" if yolo_enabled else "nudenet",
        "primary_detectors": (
            ["nudenet", "yolo11"] if yolo_enabled else ["nudenet"]
        ),
        "context_model": {
            "name": str(config.CONTEXT_MODEL_NAME),
            "enabled": bool(config.CONTEXT_MODEL_ENABLED),
            "role": "tile_ranking",
            "can_block": False,
        },
        "detection_mode": {
            "id": "visual_violation",
            "label": "Visual violation only",
            "evaluates_viewing_intent": False,
            "full_scan": True,
            "roi_recheck": True,
            "tile_ranking": tile_ranking,
        },
        "thresholds": {
            label: float(score) for label, score in config.BLOCK_THRESHOLDS.items()
        },
        "tile": {
            "enabled": bool(config.RESCUE_ENABLED),
            "rows": int(config.RESCUE_TILE_ROWS),
            "columns": int(config.RESCUE_TILE_COLUMNS),
        },
        "roi": {
            "expansion": float(config.CONTEXT_CROP_EXPANSION),
            "borderline_margin": float(config.NUDENET_BORDERLINE_MARGIN),
        },
        "temporal": {
            "window_size": int(config.CONFIRMATION_WINDOW_SIZE),
            "required_hits": int(config.CONFIRMATION_REQUIRED_HITS),
        },
        "intent_modes": [],
    }
