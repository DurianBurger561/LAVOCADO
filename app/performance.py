"""Conservative CPU thread defaults for the desktop process."""

from __future__ import annotations

import os


def configure_cpu_threads() -> int:
    """Limit native worker pools while respecting an explicit user override."""

    raw = os.environ.get("LAVOCADO_CPU_THREADS", "2")
    try:
        limit = max(1, min(8, int(raw)))
    except ValueError:
        limit = 2
    value = str(limit)
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(variable, value)
    return limit


def configure_opencv_threads() -> None:
    """OpenCV is used for small frame transforms, not parallel batch jobs."""

    import cv2

    cv2.setNumThreads(1)
