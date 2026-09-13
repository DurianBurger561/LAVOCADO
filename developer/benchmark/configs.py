"""Benchmark configuration matrix using the product Settings schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable
from uuid import uuid4

from app.settings.schema import (
    CONTEXT_MODELS,
    GRID_CHOICES,
    INPUT_SIZES,
    OVERLAPS,
    PRIMARY_DETECTORS,
    TILE_INPUT_SIZES,
    VisionSettings,
    default_vision_settings,
    merge_vision_settings,
    sanitize_vision_settings,
)

TARGET_DETECTOR = "detector_only"
TARGET_PIPELINE = "full_protection_pipeline"
TILE_FULL_ONLY = "full_only"
TILE_GRID = "grid"


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
        patch = {
            "detector": {
                "primary": self.detector,
                "full_input_size": self.full_input_size,
                "tile_input_size": self.tile_input_size or self.full_input_size,
            },
            "context": {
                "model": self.context_model or "off",
                "tile_ranking": self.context_model not in {None, "off"},
            },
            "tiles": {
                "enabled": self.tile_rows is not None and self.tile_columns is not None,
                "rows": self.tile_rows or 2,
                "columns": self.tile_columns or 2,
                "overlap": self.tile_overlap,
                "checks_per_scan": self.checks_per_scan or 1,
            },
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
    benchmark_target: str = TARGET_PIPELINE
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
    target = (
        TARGET_DETECTOR
        if selection.benchmark_target == TARGET_DETECTOR
        else TARGET_PIPELINE
    )
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
                    grids = GRID_CHOICES if tile_mode == TILE_GRID else GRID_CHOICES
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
        checks_per_scan=checks,
        threshold_profile=selection.threshold_profile,
        settings=dict(selection.settings or {}),
    )
    return config


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
    return ConfigSelection(
        benchmark_target=str(data.get("benchmark_target") or TARGET_PIPELINE),
        detectors=tuple(data.get("detectors") or ("nudenet_640m",)),
        context_models=tuple(data.get("context_models") or ("off",)),
        full_input_sizes=tuple(int(size) for size in (data.get("full_input_sizes") or (640,))),
        tile_modes=tuple(str(mode) for mode in tile_modes),
        overlaps=tuple(overlaps),
        tile_input_sizes=tuple(int(size) for size in (data.get("tile_input_sizes") or (640,))),
        threshold_profile=str(data.get("threshold_profile") or "current"),
        settings=dict(data.get("settings") or {}),
    )


def settings_to_protection_payload(config: BenchmarkConfig) -> dict[str, Any]:
    return sanitize_vision_settings(config.vision_settings().to_dict()).to_dict()
