"""Windows native capture through DXGI Desktop Duplication (DXcam)."""

from __future__ import annotations

import ctypes
import importlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.platforms.capture.errors import (
    CaptureFatalError,
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
)
from app.platforms.capture.models import CaptureBackendStatus, CaptureFrame, MonitorInfo

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _DXGIOutput:
    device_index: int
    output_index: int
    width: int
    height: int
    is_primary: bool


class _NativeRect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MonitorInfoEx(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _NativeRect),
        ("rcWork", _NativeRect),
        ("dwFlags", ctypes.c_ulong),
        ("szDevice", ctypes.c_wchar * 32),
    ]


class WindowsDXGICapture:
    """Continuously capture each Windows display with Desktop Duplication."""

    name = "windows_dxgi"

    def __init__(
        self,
        *,
        module_loader: Callable[[str], Any] = importlib.import_module,
        monitor_provider: Callable[[], list[MonitorInfo]] | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        target_fps: int = 30,
    ) -> None:
        self._module_loader = module_loader
        self._monitor_provider = monitor_provider or _enumerate_windows_monitors
        self._clock_ns = clock_ns
        self._target_fps = target_fps
        self._cameras: dict[str, Any] = {}
        self._monitors: list[MonitorInfo] = []
        self._sequences: dict[str, int] = {}
        self._last_frame_ns: dict[str, int] = {}

    def start(self) -> None:
        if self._cameras:
            return
        try:
            dxcam = self._module_loader("dxcam")
        except (ImportError, OSError) as error:
            raise CaptureUnavailableError(f"DXcam is unavailable: {error}") from error

        try:
            physical_monitors = self._monitor_provider()
            if not physical_monitors:
                raise CaptureUnavailableError("Windows found no physical displays")
            outputs = _read_outputs(dxcam, physical_monitors)
            bindings = _bind_outputs(outputs, physical_monitors)
            for output, monitor in bindings:
                camera = dxcam.create(
                    device_idx=output.device_index,
                    output_idx=output.output_index,
                    output_color="BGR",
                    backend="dxgi",
                    processor_backend="numpy",
                    max_buffer_len=2,
                )
                camera.start(target_fps=self._target_fps, video_mode=False)
                self._cameras[monitor.id] = camera
                self._monitors.append(monitor)
        except CaptureUnavailableError:
            self._release_cameras()
            raise
        except Exception as error:
            self._release_cameras()
            raise _translate_start_error(error) from error

        self._sequences = {monitor.id: 0 for monitor in self._monitors}
        self._last_frame_ns = {}

    def stop(self) -> None:
        self._release_cameras()
        self._monitors = []
        self._sequences = {}
        self._last_frame_ns = {}

    def monitors(self) -> list[MonitorInfo]:
        self._require_started()
        return list(self._monitors)

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame:
        camera = self._cameras.get(str(monitor_id))
        if camera is None:
            if not self._cameras:
                raise CaptureFatalError("Windows DXGI capture has not been started")
            raise CaptureFatalError(f"Unknown Windows monitor id: {monitor_id}")
        try:
            image = camera.grab(new_frame_only=False)
        except Exception as error:
            raise _translate_runtime_error(error) from error
        if image is None:
            raise CaptureRecoverableError("DXGI did not return a frame")
        if not isinstance(image, np.ndarray):
            raise CaptureFatalError("DXGI returned a non-array frame")
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise CaptureFatalError("DXGI returned an invalid BGR frame")

        now = self._clock_ns()
        key = str(monitor_id)
        sequence = self._sequences[key] + 1
        self._sequences[key] = sequence
        self._last_frame_ns[key] = now
        return CaptureFrame(
            image=np.ascontiguousarray(image),
            monitor_id=key,
            timestamp_ns=now,
            sequence=sequence,
            # DXcam currently consumes DXGI dirty rectangles internally but does
            # not expose them through its public API.
            changed_regions=None,
            backend=self.name,
        )

    def status(self) -> CaptureBackendStatus:
        started = bool(self._cameras)
        now = self._clock_ns()
        newest = max(self._last_frame_ns.values(), default=None)
        age_ms = None if newest is None else max(0.0, (now - newest) / 1_000_000)
        return CaptureBackendStatus(
            preferred_backend=self.name,
            active_backend=self.name if started else None,
            fallback=False,
            fallback_reason=None,
            healthy=started,
            session="windows-desktop" if started else None,
            monitor_count=len(self._monitors),
            frame_age_ms=age_ms,
        )

    def _require_started(self) -> None:
        if not self._cameras:
            raise CaptureFatalError("Windows DXGI capture has not been started")

    def _release_cameras(self) -> None:
        cameras = list(self._cameras.values())
        self._cameras = {}
        for camera in cameras:
            try:
                camera.stop()
            except Exception:
                LOGGER.debug("Could not stop DXGI camera", exc_info=True)
            try:
                camera.release()
            except Exception:
                LOGGER.debug("Could not release DXGI camera", exc_info=True)


def _read_outputs(dxcam: Any, monitors: list[MonitorInfo]) -> list[_DXGIOutput]:
    try:
        description = str(dxcam.output_info())
    except (AttributeError, TypeError):
        description = ""
    pattern = re.compile(
        r"Device\[(\d+)]\s+Output\[(\d+)].*?Res:\((\d+),\s*(\d+)\)"
        r".*?Primary:(True|False)",
        re.IGNORECASE,
    )
    outputs = [
        _DXGIOutput(
            device_index=int(match.group(1)),
            output_index=int(match.group(2)),
            width=int(match.group(3)),
            height=int(match.group(4)),
            is_primary=match.group(5).casefold() == "true",
        )
        for match in pattern.finditer(description)
    ]
    if outputs:
        return outputs
    return [
        _DXGIOutput(0, index, monitor.width, monitor.height, monitor.is_primary)
        for index, monitor in enumerate(monitors)
    ]


def _bind_outputs(
    outputs: list[_DXGIOutput],
    monitors: list[MonitorInfo],
) -> list[tuple[_DXGIOutput, MonitorInfo]]:
    """Match DXGI outputs to Win32 display geometry without exposing native APIs."""

    remaining = list(monitors)
    bindings: list[tuple[_DXGIOutput, MonitorInfo]] = []
    for output in outputs:
        match = next(
            (
                monitor
                for monitor in remaining
                if monitor.width == output.width
                and monitor.height == output.height
                and monitor.is_primary == output.is_primary
            ),
            None,
        )
        if match is None:
            match = next(
                (
                    monitor
                    for monitor in remaining
                    if monitor.width == output.width and monitor.height == output.height
                ),
                None,
            )
        if match is None and remaining:
            match = remaining[0]
        if match is not None:
            bindings.append((output, match))
            remaining.remove(match)
    if not bindings:
        raise CaptureUnavailableError("DXGI found no usable display outputs")
    return bindings


def _enumerate_windows_monitors() -> list[MonitorInfo]:
    try:
        user32 = ctypes.windll.user32
    except AttributeError as error:
        raise CaptureUnavailableError("Win32 display APIs are unavailable") from error

    monitors: list[MonitorInfo] = []
    callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_NativeRect),
        ctypes.c_ssize_t,
    )

    def add_monitor(
        handle: int,
        _device_context: int,
        _rect: object,
        _data: int,
    ) -> int:
        info = _MonitorInfoEx()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            return 1
        bounds = info.rcMonitor
        index = len(monitors) + 1
        monitors.append(
            MonitorInfo(
                id=str(index),
                index=index,
                left=int(bounds.left),
                top=int(bounds.top),
                width=int(bounds.right - bounds.left),
                height=int(bounds.bottom - bounds.top),
                is_primary=bool(info.dwFlags & 1),
            )
        )
        return 1

    callback = callback_type(add_monitor)
    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        raise CaptureUnavailableError("EnumDisplayMonitors failed")
    return monitors


def _is_permission_error(error: Exception) -> bool:
    message = str(error).casefold()
    return isinstance(error, PermissionError) or any(
        marker in message
        for marker in ("permission denied", "access denied", "e_accessdenied")
    )


def _translate_start_error(error: Exception) -> Exception:
    if _is_permission_error(error):
        return CapturePermissionDeniedError(f"DXGI permission denied: {error}")
    return CaptureUnavailableError(f"DXGI initialization failed: {error}")


def _translate_runtime_error(error: Exception) -> Exception:
    if _is_permission_error(error):
        return CapturePermissionDeniedError(f"DXGI permission denied: {error}")
    return CaptureRecoverableError(f"DXGI capture failed: {error}")
