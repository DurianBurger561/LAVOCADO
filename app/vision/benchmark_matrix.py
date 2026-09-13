"""Screen-domain benchmark matrix. Defaults stay experimental until measured."""

from __future__ import annotations

from typing import Any

PRIMARY_CONFIGS = (
    {"primary": "nudenet_640m", "full_input_size": 640, "tile_input_size": 640},
    {"primary": "yolo11_nsfw_small", "full_input_size": 640, "tile_input_size": 640},
    {"primary": "yolo11_nsfw_small", "full_input_size": 960, "tile_input_size": 640},
    {"primary": "yolo11_nsfw_small", "full_input_size": 1280, "tile_input_size": 640},
    {"primary": "yolo11_nsfw_small", "full_input_size": 960, "tile_input_size": 960},
)

CONTEXT_CONFIGS = ("off", "viddexa_nano", "viddexa_mini")

ALGORITHM_STAGES = (
    "baseline_full",
    "overlap_tiles",
    "viddexa_ranking",
    "proposal_local_recheck",
    "candidate_tracking",
    "focused_verify",
    "change_map",
    "evidence_accumulator",
)

REQUIRED_METRICS = (
    "recall",
    "precision",
    "false_positive_rate",
    "false_negative_rate",
    "small_target_recall",
    "medium_target_recall",
    "large_target_recall",
    "top1_tile_hit_rate",
    "top2_tile_hit_rate",
    "median_detection_delay_ms",
    "p95_detection_delay_ms",
    "p50_scan_latency_ms",
    "p95_scan_latency_ms",
    "cpu",
    "ram",
)

SCREEN_SCENES = (
    "full-screen image",
    "medium window",
    "small embedded image",
    "thumbnail",
    "gallery",
    "video window",
    "chat attachment",
    "image viewer zoomed out",
    "partially clipped content",
    "window overlay",
    "multi-monitor",
)


def experimental_disclaimer() -> str:
    return (
        "These combinations are measurement targets. Do not publish a "
        "Recommended default until screen-domain benchmark completes."
    )


def matrix() -> dict[str, Any]:
    return {
        "primary": list(PRIMARY_CONFIGS),
        "context": list(CONTEXT_CONFIGS),
        "algorithm_stages": list(ALGORITHM_STAGES),
        "metrics": list(REQUIRED_METRICS),
        "scenes": list(SCREEN_SCENES),
        "recommended": None,
        "disclaimer": experimental_disclaimer(),
        "product_block": None,
    }


def job_count() -> int:
    return (
        len(PRIMARY_CONFIGS)
        * len(CONTEXT_CONFIGS)
        * len(ALGORITHM_STAGES)
        * len(SCREEN_SCENES)
    )
