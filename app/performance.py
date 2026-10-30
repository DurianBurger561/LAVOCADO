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


def configure_torch_threads() -> None:
    """Bound CPU inference even when a model loader changes Torch defaults."""
    import torch

    limit = configure_cpu_threads()
    if torch.get_num_threads() != limit:
        torch.set_num_threads(limit)
    # Inter-op can only be set before parallel work starts. Repeated model
    # initialization must not fail once Torch has initialized its executor.
    if torch.get_num_interop_threads() != 1:
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
