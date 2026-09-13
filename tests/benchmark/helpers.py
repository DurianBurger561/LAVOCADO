"""Shared fixtures for Benchmark Lab tests."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def write_png(path: Path, color: tuple[int, int, int] = (20, 30, 40)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path)
    return path
