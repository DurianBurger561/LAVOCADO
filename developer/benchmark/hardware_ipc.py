"""Scalar-only IPC for packaged Developer hardware experiments."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def worker_command(kind: str, *arguments: str) -> list[str]:
    if kind not in {"capture", "stability", "diagnostic"}:
        raise ValueError(f"Unknown hardware experiment: {kind}")
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve().parents[2] / "developer_main.py"))
    return [*command, "--benchmark-worker", kind, *arguments]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically publish metadata; workers must never pass image data here."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(temporary, target)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
