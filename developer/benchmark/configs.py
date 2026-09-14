"""Benchmark configuration matrix using the product Settings schema."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from app.settings.presets import apply_preset
from app.settings.schema import (
    CONFIRMATION_MODES,
    CONTEXT_MODELS,
    CROP_EXPANSIONS,
    EVIDENCE_DECAYS,
    EVIDENCE_THRESHOLDS,
    GRID_CHOICES,
    INPUT_SIZES,
    OVERLAPS,
    PRESETS,
    PRIMARY_DETECTORS,
    PROPOSAL_MARGINS,
    THRESHOLD_STEPS,
    TILE_INPUT_SIZES,
    VisionSettings,
    default_vision_settings,
    merge_vision_settings,
    sanitize_vision_settings,
)

TARGET_DETECTOR = "detector_only"
TARGET_VISION_PIPELINE = "vision_pipeline"
TARGET_CONTEXT_POLICY = "context_policy"
TARGET_FULL_PROTECTION_PIPELINE = "full_protection_pipeline"
BENCHMARK_TARGETS = frozenset({
    TARGET_DETECTOR,
    TARGET_VISION_PIPELINE,
    TARGET_CONTEXT_POLICY,
    TARGET_FULL_PROTECTION_PIPELINE,
})
TILE_FULL_ONLY = "full_only"
THRESHOLD_PROFILES = ("current",) + PRESETS


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    id: str
    benchmark_target: str
    detector: str
    context_model: str | None
    full_input_size: int
    tile_input_size: int | None
    tile_rows: int | None
    tile_columns: int | None
    tile_overlap: float
    checks_per_scan: int | None
    threshold_profile: str
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload

    def cache_geometry(self) -> str:
        return json.dumps(
            {
                "detector": self.detector,
                "full_input_size": self.full_input_size,
                "tile_input_size": self.tile_input_size,
                "tile_rows": self.tile_rows,
                "tile_columns": self.tile_columns,
                "tile_overlap": self.tile_overlap,
            },
            sort_keys=True,
        )

    def config_hash(self) -> str:
        payload = dict(self.to_dict())
        payload.pop("id", None)
        encoded = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def vision_settings(self) -> VisionSettings:
        base = default_vision_settings()
        if self.threshold_profile in PRESETS:
            base = apply_preset(self.threshold_profile, base)
        ranking = self.context_model not in {None, "off"}
        context_patch = {
            "model": self.context_model or "off",
            "tile_ranking": ranking,
        }
        extra_context = (self.settings or {}).get("context") if isinstance(self.settings, dict) else None
        if isinstance(extra_context, dict) and "tile_ranking" in extra_context:
            context_patch["tile_ranking"] = bool(extra_context["tile_ranking"]) and ranking
        tile_extra = (self.settings or {}).get("tiles") if isinstance(self.settings, dict) else {}
        if not isinstance(tile_extra, dict):
            tile_extra = {}
        tiles_patch: dict[str, Any] = {
            "enabled": self.tile_rows is not None and self.tile_columns is not None,
            "rows": self.tile_rows or 2,
            "columns": self.tile_columns or 2,
            "overlap": self.tile_overlap,
        }
        if tile_extra.get("checks_per_scan") is not None:
            tiles_patch["checks_per_scan"] = int(tile_extra["checks_per_scan"])
        elif self.checks_per_scan is not None:
            tiles_patch["checks_per_scan"] = int(self.checks_per_scan)
        if tile_extra.get("max_skip") is not None:
            tiles_patch["max_skip"] = int(tile_extra["max_skip"])
        patch = {
            "detector": {
                "primary": self.detector,
                "full_input_size": self.full_input_size,
                "tile_input_size": self.tile_input_size or self.full_input_size,
            },
            "context": context_patch,
            "tiles": tiles_patch,
        }
        if self.settings:
            merged = dict(self.settings)
            for key, value in patch.items():
                if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                    nested = dict(merged[key])
                    nested.update(value)
                    merged[key] = nested
                else:
                    merged[key] = value
            patch = merged
        return merge_vision_settings(base, patch)


@dataclass(frozen=True, slots=True)
class ConfigSelection:
    benchmark_target: str = TARGET_FULL_PROTECTION_PIPELINE
    detectors: tuple[str, ...] = ("nudenet_640m",)
    context_models: tuple[str, ...] = ("off",)
    full_input_sizes: tuple[int, ...] = (640,)
    tile_modes: tuple[str, ...] = (TILE_FULL_ONLY,)
    overlaps: tuple[float, ...] = (0.0,)
    tile_input_sizes: tuple[int, ...] = (640,)
    threshold_profile: str = "current"
    settings: dict[str, Any] = field(default_factory=dict)


def _unique(values: Iterable[Any]) -> tuple[Any, ...]:
    seen: list[Any] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return tuple(seen)


def expand_configs(selection: ConfigSelection) -> list[BenchmarkConfig]:
    target = selection.benchmark_target
    if target not in BENCHMARK_TARGETS:
        raise ValueError(f"Unknown benchmark target: {target}")
    if target == TARGET_CONTEXT_POLICY:
        return [
            _make_config(
                target,
                "nudenet_640m",
                None,
                640,
                None,
                None,
                None,
                0.0,
                None,
                selection,
            )
        ]
    detectors = [
        name
        for name in _unique(selection.detectors)
        if name in PRIMARY_DETECTORS
    ]
    contexts = [
        name
        for name in _unique(selection.context_models)
        if name in CONTEXT_MODELS
    ]
    full_sizes = [
        size for size in _unique(selection.full_input_sizes) if size in INPUT_SIZES
    ]
    tile_modes = _unique(selection.tile_modes) or (TILE_FULL_ONLY,)
    overlaps = [value for value in _unique(selection.overlaps) if value in OVERLAPS]
    tile_inputs = [
        size for size in _unique(selection.tile_input_sizes) if size in TILE_INPUT_SIZES
    ]
    if not detectors or not contexts or not full_sizes:
        return []

    configs: list[BenchmarkConfig] = []
    for detector in detectors:
        detector_full = [640] if detector == "nudenet_640m" else full_sizes
        detector_tile = [640] if detector == "nudenet_640m" else tile_inputs
        for context in contexts:
            context_name = None if context == "off" else context
            for full_size in detector_full:
                for tile_mode in tile_modes:
                    if tile_mode == TILE_FULL_ONLY:
                        configs.append(
                            _make_config(
                                target,
                                detector,
                                context_name,
                                full_size,
                                None,
                                None,
                                None,
                                0.0,
                                None,
                                selection,
                            )
                        )
                        continue
                    grids = GRID_CHOICES
                    if tile_mode in {"2x2", "2×2"}:
                        grids = ((2, 2),)
                    elif tile_mode in {"3x3", "3×3"}:
                        grids = ((3, 3),)
                    effective_overlaps = overlaps or (0.15,)
                    for rows, columns in grids:
                        for overlap in effective_overlaps:
                            for tile_size in detector_tile or (640,):
                                configs.append(
                                    _make_config(
                                        target,
                                        detector,
                                        context_name,
                                        full_size,
                                        tile_size,
                                        rows,
                                        columns,
                                        overlap,
                                        1,
                                        selection,
                                    )
                                )
    return configs


def _make_config(
    target: str,
    detector: str,
    context_name: str | None,
    full_size: int,
    tile_size: int | None,
    rows: int | None,
    columns: int | None,
    overlap: float,
    checks: int | None,
    selection: ConfigSelection,
) -> BenchmarkConfig:
    config = BenchmarkConfig(
        id=uuid4().hex[:12],
        benchmark_target=target,
        detector=detector,
        context_model=context_name,
        full_input_size=full_size,
        tile_input_size=tile_size,
        tile_rows=rows,
        tile_columns=columns,
        tile_overlap=float(overlap),
        checks_per_scan=_checks_per_scan(selection, checks),
        threshold_profile=(
            selection.threshold_profile
            if selection.threshold_profile in THRESHOLD_PROFILES
            else "current"
        ),
        settings=dict(selection.settings or {}),
    )
    return config


def _checks_per_scan(selection: ConfigSelection, fallback: int | None) -> int | None:
    tiles = (selection.settings or {}).get("tiles") if isinstance(selection.settings, dict) else None
    if isinstance(tiles, dict) and tiles.get("checks_per_scan") is not None:
        return int(tiles["checks_per_scan"])
    return fallback


def selection_from_payload(payload: dict[str, Any] | None) -> ConfigSelection:
    data = payload if isinstance(payload, dict) else {}
    overlaps_raw = data.get("overlaps") or data.get("overlap") or [0.0]
    if isinstance(overlaps_raw, (int, float, str)):
        overlaps_raw = [overlaps_raw]
    overlaps = []
    for item in overlaps_raw:
        try:
            value = float(item)
        except (TypeError, ValueError):
            continue
        if value > 1:
            value = value / 100.0
        overlaps.append(value)
    tile_modes = data.get("tile_modes") or data.get("tile_mode") or [TILE_FULL_ONLY]
    if isinstance(tile_modes, str):
        tile_modes = [tile_modes]
    profile = str(data.get("threshold_profile") or "current").strip().lower()
    if profile not in THRESHOLD_PROFILES:
        profile = "current"
    return ConfigSelection(
        benchmark_target=str(data.get("benchmark_target") or TARGET_FULL_PROTECTION_PIPELINE),
        detectors=tuple(data.get("detectors") or ("nudenet_640m",)),
        context_models=tuple(data.get("context_models") or ("off",)),
        full_input_sizes=tuple(int(size) for size in (data.get("full_input_sizes") or (640,))),
        tile_modes=tuple(str(mode) for mode in tile_modes),
        overlaps=tuple(overlaps),
        tile_input_sizes=tuple(int(size) for size in (data.get("tile_input_sizes") or (640,))),
        threshold_profile=profile,
        settings=algorithm_settings_from_payload(data),
    )


def algorithm_settings_from_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Map Lab UI fields onto the product VisionSettings patch."""

    nested = dict(data.get("settings") or {}) if isinstance(data.get("settings"), dict) else {}
    source = dict(data)
    source.update(nested)
    recheck: dict[str, Any] = dict(nested.get("recheck") or {})
    temporal: dict[str, Any] = dict(nested.get("temporal") or {})
    tiles: dict[str, Any] = dict(nested.get("tiles") or {})
    context: dict[str, Any] = dict(nested.get("context") or {})
    if source.get("proposal_margin") is not None:
        recheck["proposal_margin"] = float(source["proposal_margin"])
    if source.get("crop_expansion") is not None:
        recheck["crop_expansion"] = float(source["crop_expansion"])
    if source.get("checks_per_scan") is not None:
        tiles["checks_per_scan"] = int(source["checks_per_scan"])
    if source.get("max_skip") is not None:
        tiles["max_skip"] = int(source["max_skip"])
    if source.get("evidence_threshold") is not None:
        temporal["evidence_threshold"] = float(source["evidence_threshold"])
    if source.get("decay") is not None:
        temporal["decay"] = float(source["decay"])
    if source.get("confirmation") is not None:
        temporal["confirmation"] = str(source["confirmation"])
    if source.get("min_fresh_hits") is not None:
        temporal["min_fresh_hits"] = int(source["min_fresh_hits"])
    if source.get("window_size") is not None:
        temporal["window_size"] = int(source["window_size"])
    if (
        "min_fresh_hits" in temporal
        and "window_size" in temporal
        and int(temporal["min_fresh_hits"]) > int(temporal["window_size"])
    ):
        temporal["min_fresh_hits"] = int(temporal["window_size"])
    if source.get("tile_ranking") is not None:
        raw = source["tile_ranking"]
        context["tile_ranking"] = str(raw).strip().lower() not in {"0", "false", "off", ""}
    payload: dict[str, Any] = {}
    if recheck:
        payload["recheck"] = recheck
    if temporal:
        payload["temporal"] = temporal
    if tiles:
        payload["tiles"] = tiles
    if context:
        payload["context"] = context
    return payload


def schema_options() -> dict[str, Any]:
    """Expose the same discrete choices the user Settings schema allows."""

    return {
        "threshold_profiles": list(THRESHOLD_PROFILES),
        "proposal_margins": list(PROPOSAL_MARGINS),
        "crop_expansions": list(CROP_EXPANSIONS),
        "evidence_thresholds": list(EVIDENCE_THRESHOLDS),
        "evidence_decays": list(EVIDENCE_DECAYS),
        "confirmation_modes": list(CONFIRMATION_MODES),
        "threshold_steps": list(THRESHOLD_STEPS),
        "strong_defaults": [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70],
        "proposal_defaults": [0.35, 0.40, 0.45],
    }


def settings_to_protection_payload(config: BenchmarkConfig) -> dict[str, Any]:
    return sanitize_vision_settings(config.vision_settings().to_dict()).to_dict()
