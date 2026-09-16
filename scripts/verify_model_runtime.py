"""Fail release preparation if any required local model cannot load offline."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.self_check import verify_required_models


def verify_model_runtime() -> None:
    verify_required_models()


if __name__ == "__main__":
    verify_model_runtime()
    print("Verified all four model runtimes offline.")
