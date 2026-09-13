"""Local annotated preview. Never written to Protection history or uploaded."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw


def image_data_url(path: Path, *, max_edge: int = 640, quality: int = 80) -> str:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        rgb.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=quality)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def annotated_data_url(
    path: Path,
    *,
    detections: Iterable[dict[str, Any]] | None = None,
    tiles: Iterable[dict[str, Any]] | None = None,
    selected_tile: dict[str, Any] | None = None,
    max_edge: int = 960,
) -> str:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        original_size = rgb.size
        rgb.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        scale_x = rgb.size[0] / max(1, original_size[0])
        scale_y = rgb.size[1] / max(1, original_size[1])
        draw = ImageDraw.Draw(rgb)
        for tile in tiles or []:
            box = _scale_box(tile.get("box"), scale_x, scale_y)
            if box is not None:
                draw.rectangle(box, outline="#96a3bb", width=1)
        if selected_tile is not None:
            box = _scale_box(selected_tile.get("box"), scale_x, scale_y)
            if box is not None:
                draw.rectangle(box, outline="#c8b6ff", width=3)
        for detection in detections or []:
            box = _scale_box(detection.get("box"), scale_x, scale_y)
            if box is None:
                continue
            draw.rectangle(box, outline="#f49099", width=2)
            label = str(detection.get("class") or "")
            score = detection.get("score")
            caption = label
            if isinstance(score, (int, float)):
                caption = f"{label} {score:.2f}"
            draw.text((box[0] + 3, box[1] + 3), caption, fill="#f4f7fb")
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=85)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _scale_box(box: object, scale_x: float, scale_y: float) -> tuple[float, float, float, float] | None:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x, y, width, height = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    left = x * scale_x
    top = y * scale_y
    return (left, top, left + width * scale_x, top + height * scale_y)
