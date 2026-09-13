"""Privacy-safe Vision settings snapshot. No viewing-intent modes."""

from __future__ import annotations

from typing import Any

from app import config
from app.settings.schema import VisionSettings, default_vision_settings
from app.vision.yolo_adapter import yolo_is_requested


def vision_settings_snapshot(settings: VisionSettings | None = None) -> dict[str, Any]:
    """Return the Vision Settings group, never medical/art/education modes."""

    current = settings or default_vision_settings()
    yolo_requested = (
        current.detector.primary == "yolo11_nsfw_small" or yolo_is_requested()
    )
    primary = current.detector.primary
    tile_ranking = bool(current.tiles.enabled and current.context.model != "off")
    return {
        "primary_detector": primary,
        "primary_detectors": [primary],
        "yolo": {
            "requested": yolo_requested,
            "maps_sexual_act": True,
        },
        "context_model": {
            "name": current.context.model,
            "huggingface_id": (
                config.CONTEXT_NANO_MODEL_NAME
                if current.context.model == "viddexa_nano"
                else config.CONTEXT_MINI_MODEL_NAME
                if current.context.model == "viddexa_mini"
                else "off"
            ),
            "enabled": current.context.model != "off",
            "role": "tile_ranking",
            "can_block": False,
        },
        "detection_mode": {
            "id": "visual_violation",
            "label": "Visual violation only",
            "evaluates_viewing_intent": False,
            "full_scan": True,
            "roi_recheck": bool(current.recheck.enabled),
            "tile_ranking": tile_ranking,
        },
        "thresholds": {
            label: float(score) for label, score in config.BLOCK_THRESHOLDS.items()
        },
        "tile": {
            "enabled": bool(current.tiles.enabled),
            "rows": int(current.tiles.rows),
            "columns": int(current.tiles.columns),
            "overlap": float(current.tiles.overlap),
            "checks_per_scan": int(current.tiles.checks_per_scan),
            "max_skip": int(current.tiles.max_skip),
        },
        "roi": {
            "expansion": float(current.recheck.crop_expansion),
            "borderline_margin": float(current.recheck.proposal_margin),
        },
        "temporal": {
            "window_size": int(current.temporal.window_size),
            "required_hits": int(current.temporal.min_fresh_hits),
            "evidence_threshold": float(current.temporal.evidence_threshold),
            "decay": float(current.temporal.decay),
        },
        "scan": {
            "normal_interval_ms": int(current.scan.normal_interval_ms),
            "candidate_interval_ms": int(current.scan.candidate_interval_ms),
            "adaptive": bool(current.scan.adaptive),
            "active_monitor_priority": bool(current.scan.active_monitor_priority),
        },
        "detector_input": {
            "full": int(current.detector.full_input_size),
            "tile": int(current.detector.tile_input_size),
        },
        "preset": current.preset,
        "experimental": True,
        "intent_modes": [],
        "schema": current.to_dict(),
    }
