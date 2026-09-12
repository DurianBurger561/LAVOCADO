"""macOS native capture through ScreenCaptureKit streaming."""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Callable, Mapping
from threading import Condition, Event, Lock
from typing import Any, Protocol

import numpy as np

from app.platforms.capture.errors import (
    CaptureError,
    CaptureFatalError,
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
)
from app.platforms.capture.models import (
    CaptureBackendStatus,
    CaptureFrame,
    MonitorInfo,
    Rect,
)

LOGGER = logging.getLogger(__name__)
_DELEGATE_CLASS: Any | None = None

FrameHandler = Callable[[str, np.ndarray, tuple[Rect, ...] | None], None]
ErrorHandler = Callable[[CaptureError], None]


class _CaptureBridge(Protocol):
    def start(
        self,
        frame_handler: FrameHandler,
        error_handler: ErrorHandler,
    ) -> list[MonitorInfo]: ...

    def stop(self) -> None: ...


class ScreenCaptureKitCapture:
    """Expose one latest-frame slot per ScreenCaptureKit display stream."""

    name = "macos_screencapturekit"

    def __init__(
        self,
        *,
        bridge_factory: Callable[[], _CaptureBridge] | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        first_frame_timeout: float = 2.5,
    ) -> None:
        self._bridge_factory = bridge_factory or _PyObjCScreenCaptureKitBridge
        self._clock_ns = clock_ns
        self._first_frame_timeout = first_frame_timeout
        self._condition = Condition(Lock())
        self._bridge: _CaptureBridge | None = None
        self._monitors: list[MonitorInfo] = []
        self._frames: dict[str, CaptureFrame] = {}
        self._sequences: dict[str, int] = {}
        self._error: CaptureError | None = None

    def start(self) -> None:
        if self._bridge is not None:
            return
        bridge = self._bridge_factory()
        with self._condition:
            self._frames = {}
            self._sequences = {}
            self._error = None
        try:
            monitors = bridge.start(self._publish_frame, self._publish_error)
        except CaptureError:
            bridge.stop()
            raise
        except Exception as error:
            bridge.stop()
            raise CaptureUnavailableError(
                f"ScreenCaptureKit initialization failed: {error}"
            ) from error
        if not monitors:
            bridge.stop()
            raise CaptureUnavailableError("ScreenCaptureKit found no displays")
        self._monitors = list(monitors)
        self._bridge = bridge

    def stop(self) -> None:
        bridge = self._bridge
        self._bridge = None
        self._monitors = []
        if bridge is not None:
            try:
                bridge.stop()
            except Exception:
                LOGGER.debug("Could not stop ScreenCaptureKit", exc_info=True)
        with self._condition:
            self._frames = {}
            self._sequences = {}
            self._error = None
            self._condition.notify_all()

    def monitors(self) -> list[MonitorInfo]:
        self._require_started()
        return list(self._monitors)

    def get_latest_frame(self, monitor_id: str) -> CaptureFrame:
        self._require_started()
        key = str(monitor_id)
        if key not in {monitor.id for monitor in self._monitors}:
            raise CaptureFatalError(f"Unknown macOS monitor id: {monitor_id}")

        deadline = time.monotonic() + self._first_frame_timeout
        with self._condition:
            while key not in self._frames and self._error is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            if self._error is not None:
                raise self._error
            frame = self._frames.get(key)
        if frame is None:
            raise CaptureRecoverableError(
                f"ScreenCaptureKit produced no frame for display {key}"
            )
        return frame

    def status(self) -> CaptureBackendStatus:
        started = self._bridge is not None
        with self._condition:
            error = self._error
            newest = max(
                (frame.timestamp_ns for frame in self._frames.values()),
                default=None,
            )
        now = self._clock_ns()
        age_ms = None if newest is None else max(0.0, (now - newest) / 1_000_000)
        return CaptureBackendStatus(
            preferred_backend=self.name,
            active_backend=self.name if started else None,
            fallback=False,
            fallback_reason=None,
            healthy=started and error is None,
            error=None if error is None else str(error),
            session="macos-screen-recording" if started else None,
            monitor_count=len(self._monitors),
            frame_age_ms=age_ms,
        )

    def _publish_frame(
        self,
        monitor_id: str,
        image: np.ndarray,
        changed_regions: tuple[Rect, ...] | None,
    ) -> None:
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            self._publish_error(
                CaptureRecoverableError("ScreenCaptureKit returned an invalid BGR frame")
            )
            return
        key = str(monitor_id)
        with self._condition:
            sequence = self._sequences.get(key, 0) + 1
            self._sequences[key] = sequence
            self._frames[key] = CaptureFrame(
                image=np.ascontiguousarray(image),
                monitor_id=key,
                timestamp_ns=self._clock_ns(),
                sequence=sequence,
                changed_regions=changed_regions,
                backend=self.name,
            )
            self._condition.notify_all()

    def _publish_error(self, error: CaptureError) -> None:
        with self._condition:
            self._error = error
            self._condition.notify_all()

    def _require_started(self) -> None:
        if self._bridge is None:
            raise CaptureFatalError("ScreenCaptureKit capture has not been started")


class _PyObjCScreenCaptureKitBridge:
    """Thin lazy-loaded PyObjC bridge; imported only in a macOS process."""

    def __init__(
        self,
        *,
        module_loader: Callable[[str], Any] = importlib.import_module,
        target_fps: int = 30,
        operation_timeout: float = 15.0,
    ) -> None:
        self._module_loader = module_loader
        self._target_fps = target_fps
        self._operation_timeout = operation_timeout
        self._streams: list[tuple[Any, Any, Any]] = []

    def start(
        self,
        frame_handler: FrameHandler,
        error_handler: ErrorHandler,
    ) -> list[MonitorInfo]:
        try:
            objc = self._module_loader("objc")
            foundation = self._module_loader("Foundation")
            screen_capture = self._module_loader("ScreenCaptureKit")
            core_media = self._module_loader("CoreMedia")
            quartz = self._module_loader("Quartz")
            dispatch = self._module_loader("dispatch")
        except (ImportError, OSError) as error:
            raise CaptureUnavailableError(
                f"ScreenCaptureKit bindings are unavailable: {error}"
            ) from error

        _check_screen_recording_permission(quartz)
        content = self._shareable_content(screen_capture)
        displays = list(content.displays())
        if not displays:
            raise CaptureUnavailableError("ScreenCaptureKit found no shareable displays")

        main_display_id = int(quartz.CGMainDisplayID())
        display_pairs = [
            (
                display,
                _monitor_from_display(display, index, main_display_id),
            )
            for index, display in enumerate(displays, start=1)
        ]
        display_pairs.sort(key=lambda pair: (not pair[1].is_primary, pair[1].index))
        display_pairs = [
            (
                display,
                MonitorInfo(
                    id=monitor.id,
                    index=index,
                    left=monitor.left,
                    top=monitor.top,
                    width=monitor.width,
                    height=monitor.height,
                    is_primary=monitor.is_primary,
                ),
            )
            for index, (display, monitor) in enumerate(display_pairs, start=1)
        ]

        delegate_class = _delegate_class(objc, foundation)
        try:
            for display, monitor in display_pairs:
                configuration = screen_capture.SCStreamConfiguration.alloc().init()
                configuration.setWidth_(int(display.width()))
                configuration.setHeight_(int(display.height()))
                configuration.setPixelFormat_(quartz.kCVPixelFormatType_32BGRA)
                configuration.setQueueDepth_(2)
                configuration.setMinimumFrameInterval_(
                    core_media.CMTimeMake(1, self._target_fps)
                )
                configuration.setShowsCursor_(True)
                content_filter = (
                    screen_capture.SCContentFilter.alloc()
                    .initWithDisplay_excludingWindows_(display, [])
                )
                delegate = delegate_class.alloc().init()
                delegate.frame_handler = frame_handler
                delegate.error_handler = error_handler
                delegate.monitor_id = monitor.id
                delegate.screen_capture = screen_capture
                delegate.core_media = core_media
                delegate.quartz = quartz
                stream = screen_capture.SCStream.alloc().initWithFilter_configuration_delegate_(
                    content_filter,
                    configuration,
                    delegate,
                )
                queue = dispatch.dispatch_queue_create(
                    f"org.lavocado.capture.{monitor.id}".encode(),
                    None,
                )
                added = stream.addStreamOutput_type_sampleHandlerQueue_error_(
                    delegate,
                    screen_capture.SCStreamOutputTypeScreen,
                    queue,
                    None,
                )
                success, add_error = _objective_c_result(added)
                if not success:
                    raise _translate_start_error(add_error or "could not add stream output")
                self._start_stream(stream)
                self._streams.append((stream, delegate, queue))
        except CaptureError:
            self.stop()
            raise
        except Exception as error:
            self.stop()
            raise _translate_start_error(error) from error
        return [monitor for _display, monitor in display_pairs]

    def stop(self) -> None:
        streams = self._streams
        self._streams = []
        for stream, _delegate, _queue in streams:
            try:
                stream.stopCaptureWithCompletionHandler_(lambda _error: None)
            except Exception:
                LOGGER.debug("Could not stop macOS display stream", exc_info=True)

    def _shareable_content(self, screen_capture: Any) -> Any:
        event = Event()
        result: dict[str, Any] = {}

        def completed(content: Any, error: Any) -> None:
            result["content"] = content
            result["error"] = error
            event.set()

        screen_capture.SCShareableContent.getShareableContentWithCompletionHandler_(
            completed
        )
        if not event.wait(self._operation_timeout):
            raise CaptureUnavailableError("ScreenCaptureKit display discovery timed out")
        if result.get("error") is not None:
            raise _translate_start_error(result["error"])
        content = result.get("content")
        if content is None:
            raise CaptureUnavailableError("ScreenCaptureKit returned no shareable content")
        return content

    def _start_stream(self, stream: Any) -> None:
        event = Event()
        result: dict[str, Any] = {}

        def completed(error: Any) -> None:
            result["error"] = error
            event.set()

        stream.startCaptureWithCompletionHandler_(completed)
        if not event.wait(self._operation_timeout):
            raise CaptureUnavailableError("ScreenCaptureKit stream start timed out")
        if result.get("error") is not None:
            raise _translate_start_error(result["error"])


def _delegate_class(objc: Any, foundation: Any) -> Any:
    global _DELEGATE_CLASS
    if _DELEGATE_CLASS is not None:
        return _DELEGATE_CLASS

    class LavocadoScreenCaptureOutput(foundation.NSObject):
        __pyobjc_protocols__ = (
            objc.protocolNamed("SCStreamOutput"),
            objc.protocolNamed("SCStreamDelegate"),
        )

        def stream_didOutputSampleBuffer_ofType_(
            self,
            _stream: Any,
            sample_buffer: Any,
            output_type: Any,
        ) -> None:
            if output_type != self.screen_capture.SCStreamOutputTypeScreen:
                return
            try:
                converted = _sample_buffer_to_bgr(
                    sample_buffer,
                    self.core_media,
                    self.quartz,
                    self.screen_capture,
                )
                if converted is not None:
                    image, regions = converted
                    self.frame_handler(self.monitor_id, image, regions)
            except Exception as error:  # noqa: BLE001 - ObjC callback boundary
                self.error_handler(_translate_runtime_error(error))

        def stream_didStopWithError_(self, _stream: Any, error: Any) -> None:
            if error is not None:
                self.error_handler(_translate_runtime_error(error))

    _DELEGATE_CLASS = LavocadoScreenCaptureOutput
    return _DELEGATE_CLASS


def _sample_buffer_to_bgr(
    sample_buffer: Any,
    core_media: Any,
    quartz: Any,
    screen_capture: Any,
) -> tuple[np.ndarray, tuple[Rect, ...] | None] | None:
    if not core_media.CMSampleBufferIsValid(sample_buffer):
        return None
    if not _is_complete_frame(sample_buffer, core_media, screen_capture):
        return None
    pixel_buffer = core_media.CMSampleBufferGetImageBuffer(sample_buffer)
    if pixel_buffer is None:
        return None
    flags = quartz.kCVPixelBufferLock_ReadOnly
    if quartz.CVPixelBufferLockBaseAddress(pixel_buffer, flags) != 0:
        raise CaptureRecoverableError("Could not lock ScreenCaptureKit pixel buffer")
    try:
        width = int(quartz.CVPixelBufferGetWidth(pixel_buffer))
        height = int(quartz.CVPixelBufferGetHeight(pixel_buffer))
        bytes_per_row = int(quartz.CVPixelBufferGetBytesPerRow(pixel_buffer))
        base_address = quartz.CVPixelBufferGetBaseAddress(pixel_buffer)
        if base_address is None or width <= 0 or height <= 0:
            raise CaptureRecoverableError("ScreenCaptureKit returned an empty pixel buffer")
        byte_count = bytes_per_row * height
        if hasattr(base_address, "as_buffer"):
            raw = base_address.as_buffer(byte_count)
        else:
            raw = memoryview(base_address)[:byte_count]
        rows = np.frombuffer(raw, dtype=np.uint8, count=byte_count).reshape(
            height,
            bytes_per_row,
        )
        bgra = rows[:, : width * 4].reshape(height, width, 4)
        image = np.ascontiguousarray(bgra[:, :, :3])
        regions = _dirty_regions(sample_buffer, core_media, screen_capture)
        return image, regions
    finally:
        quartz.CVPixelBufferUnlockBaseAddress(pixel_buffer, flags)


def _is_complete_frame(
    sample_buffer: Any,
    core_media: Any,
    screen_capture: Any,
) -> bool:
    status_key = getattr(screen_capture, "SCStreamFrameInfoStatus", None)
    complete = getattr(screen_capture, "SCFrameStatusComplete", None)
    if status_key is None or complete is None:
        return True
    attachments = core_media.CMSampleBufferGetSampleAttachmentsArray(
        sample_buffer,
        False,
    )
    if not attachments:
        return False
    status = _mapping_value(attachments[0], status_key)
    return status is not None and int(status) == int(complete)


def _dirty_regions(
    sample_buffer: Any,
    core_media: Any,
    screen_capture: Any,
) -> tuple[Rect, ...] | None:
    dirty_key = getattr(screen_capture, "SCStreamFrameInfoDirtyRects", None)
    if dirty_key is None:
        return None
    attachments = core_media.CMSampleBufferGetSampleAttachmentsArray(
        sample_buffer,
        False,
    )
    if not attachments:
        return None
    raw_regions = _mapping_value(attachments[0], dirty_key)
    if not raw_regions:
        return None
    regions = tuple(
        region
        for value in raw_regions
        if (region := _rect_from_value(value)) is not None
    )
    return regions or None


def _mapping_value(mapping: Any, key: Any) -> Any:
    if isinstance(mapping, Mapping):
        return mapping.get(key)
    reader = getattr(mapping, "objectForKey_", None)
    return None if reader is None else reader(key)


def _rect_from_value(value: Any) -> Rect | None:
    rect = value.rectValue() if hasattr(value, "rectValue") else value
    try:
        if hasattr(rect, "origin") and hasattr(rect, "size"):
            return Rect(
                left=round(rect.origin.x),
                top=round(rect.origin.y),
                width=round(rect.size.width),
                height=round(rect.size.height),
            )
        if isinstance(rect, Mapping):
            return Rect(
                left=round(float(rect.get("X", rect.get("x", 0)))),
                top=round(float(rect.get("Y", rect.get("y", 0)))),
                width=round(float(rect.get("Width", rect.get("width", 0)))),
                height=round(float(rect.get("Height", rect.get("height", 0)))),
            )
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _monitor_from_display(
    display: Any,
    index: int,
    main_display_id: int,
) -> MonitorInfo:
    display_id = int(display.displayID())
    frame = display.frame()
    return MonitorInfo(
        id=str(display_id),
        index=index,
        left=round(frame.origin.x),
        top=round(frame.origin.y),
        width=round(frame.size.width),
        height=round(frame.size.height),
        is_primary=display_id == main_display_id,
    )


def _check_screen_recording_permission(quartz: Any) -> None:
    preflight = getattr(quartz, "CGPreflightScreenCaptureAccess", None)
    request = getattr(quartz, "CGRequestScreenCaptureAccess", None)
    if preflight is None or bool(preflight()):
        return
    if request is None or not bool(request()):
        raise CapturePermissionDeniedError(
            "Screen Recording permission was denied; enable LAVOCADO in "
            "System Settings > Privacy & Security > Screen Recording"
        )


def _objective_c_result(result: Any) -> tuple[bool, Any | None]:
    if isinstance(result, tuple):
        success = bool(result[0]) if result else False
        error = result[1] if len(result) > 1 else None
        return success, error
    return bool(result), None


def _is_permission_error(error: Any) -> bool:
    message = str(error).casefold()
    return any(
        marker in message
        for marker in (
            "permission denied",
            "not authorized",
            "not authorised",
            "user declined",
            "user denied",
            "-3801",
        )
    )


def _translate_start_error(error: Any) -> CaptureError:
    if _is_permission_error(error):
        return CapturePermissionDeniedError(
            f"Screen Recording permission denied: {error}"
        )
    return CaptureUnavailableError(f"ScreenCaptureKit initialization failed: {error}")


def _translate_runtime_error(error: Any) -> CaptureError:
    if isinstance(error, CaptureError):
        return error
    if _is_permission_error(error):
        return CapturePermissionDeniedError(
            f"Screen Recording permission denied: {error}"
        )
    return CaptureRecoverableError(f"ScreenCaptureKit stream failed: {error}")
