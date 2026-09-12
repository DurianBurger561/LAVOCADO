"""Wayland screen capture through xdg-desktop-portal and PipeWire."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Condition, Event, Lock, Thread, current_thread
from typing import Any, Protocol

import numpy as np

from app.platforms.capture.errors import (
    CaptureError,
    CaptureFatalError,
    CapturePermissionDeniedError,
    CaptureRecoverableError,
    CaptureUnavailableError,
)
from app.platforms.capture.models import CaptureBackendStatus, CaptureFrame, MonitorInfo

LOGGER = logging.getLogger(__name__)
_PORTAL_DESTINATION = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_SCREENCAST_INTERFACE = "org.freedesktop.portal.ScreenCast"
_REQUEST_INTERFACE = "org.freedesktop.portal.Request"
_SESSION_INTERFACE = "org.freedesktop.portal.Session"

FrameHandler = Callable[[str, np.ndarray], None]
ErrorHandler = Callable[[CaptureError], None]
CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]


class _CaptureBridge(Protocol):
    def start(
        self,
        frame_handler: FrameHandler,
        error_handler: ErrorHandler,
    ) -> list[MonitorInfo]: ...

    def stop(self) -> None: ...


class PipeWirePortalCapture:
    """Expose compositor-approved Wayland streams as latest BGR frames."""

    name = "linux_pipewire_portal"

    def __init__(
        self,
        *,
        bridge_factory: Callable[[], _CaptureBridge] | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        first_frame_timeout: float = 5.0,
    ) -> None:
        self._bridge_factory = bridge_factory or _PortalPipeWireBridge
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
                f"Wayland Portal initialization failed: {error}"
            ) from error
        if not monitors:
            bridge.stop()
            raise CaptureUnavailableError("Wayland Portal returned no displays")
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
                LOGGER.debug("Could not stop Wayland Portal capture", exc_info=True)
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
            raise CaptureFatalError(f"Unknown Wayland monitor id: {monitor_id}")

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
                f"PipeWire produced no frame for display {key}"
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
            session="wayland-portal" if started else None,
            monitor_count=len(self._monitors),
            frame_age_ms=age_ms,
        )

    def _publish_frame(self, monitor_id: str, image: np.ndarray) -> None:
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            self._publish_error(
                CaptureRecoverableError("PipeWire returned an invalid BGR frame")
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
                changed_regions=None,
                backend=self.name,
            )
            self._condition.notify_all()

    def _publish_error(self, error: CaptureError) -> None:
        with self._condition:
            self._error = error
            self._condition.notify_all()

    def _require_started(self) -> None:
        if self._bridge is None:
            raise CaptureFatalError("Wayland Portal capture has not been started")


@dataclass(frozen=True, slots=True)
class _PortalStream:
    monitor_id: str
    node_id: int
    left: int
    top: int
    width: int
    height: int

    def monitor(self, index: int, *, primary: bool) -> MonitorInfo:
        return MonitorInfo(
            id=self.monitor_id,
            index=index,
            left=self.left,
            top=self.top,
            width=self.width,
            height=self.height,
            is_primary=primary,
        )


class _PortalPipeWireBridge:
    """Own one Portal D-Bus session and one GStreamer reader per stream."""

    def __init__(
        self,
        *,
        executable_finder: Callable[[str], str | None] = shutil.which,
        command_runner: CommandRunner = subprocess.run,
        startup_timeout: float = 120.0,
        target_fps: int = 5,
    ) -> None:
        self._executable_finder = executable_finder
        self._command_runner = command_runner
        self._startup_timeout = startup_timeout
        self._target_fps = target_fps
        self._ready = Event()
        self._thread: Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_stop: asyncio.Event | None = None
        self._task: asyncio.Task[Any] | None = None
        self._startup_error: CaptureError | None = None
        self._monitors: list[MonitorInfo] = []
        self._readers: list[_GStreamerReader] = []
        self._frame_handler: FrameHandler | None = None
        self._error_handler: ErrorHandler | None = None
        self._bus: Any | None = None
        self._session_handle: str | None = None
        self._responses: dict[str, tuple[int, Mapping[str, Any]]] = {}
        self._response_waiters: dict[str, asyncio.Future[Any]] = {}

    def start(
        self,
        frame_handler: FrameHandler,
        error_handler: ErrorHandler,
    ) -> list[MonitorInfo]:
        if self._thread is not None:
            return list(self._monitors)
        gst_launch = self._executable_finder("gst-launch-1.0")
        gst_inspect = self._executable_finder("gst-inspect-1.0")
        if not gst_launch or not gst_inspect:
            raise CaptureUnavailableError(
                "GStreamer tools are unavailable; install gst-launch-1.0 and "
                "gst-inspect-1.0"
            )
        try:
            inspection = self._command_runner(
                [gst_inspect, "--exists", "pipewiresrc"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise CaptureUnavailableError(
                f"Could not inspect the GStreamer PipeWire plugin: {error}"
            ) from error
        if inspection.returncode != 0:
            raise CaptureUnavailableError(
                "GStreamer pipewiresrc is unavailable; install the PipeWire plugin"
            )
        self._frame_handler = frame_handler
        self._error_handler = error_handler
        self._ready.clear()
        self._startup_error = None
        self._thread = Thread(
            target=self._thread_main,
            args=(gst_launch,),
            name="lavocado-wayland-portal",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(self._startup_timeout):
            self.stop()
            raise CapturePermissionDeniedError(
                "Wayland screen selection was not approved before timeout"
            )
        if self._startup_error is not None:
            error = self._startup_error
            self.stop()
            raise error
        return list(self._monitors)

    def stop(self) -> None:
        loop = self._loop
        stop_event = self._async_stop
        task = self._task
        if loop is not None and task is not None and not self._ready.is_set():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        elif loop is not None and stop_event is not None:
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=5.0)
        self._thread = None
        self._monitors = []
        self._frame_handler = None
        self._error_handler = None

    def _thread_main(self, gst_launch: str) -> None:
        try:
            asyncio.run(self._run(gst_launch))
        except asyncio.CancelledError:
            pass
        except CaptureError as error:
            if not self._ready.is_set():
                self._startup_error = error
            elif self._error_handler is not None:
                self._error_handler(error)
        except Exception as error:
            translated = CaptureUnavailableError(
                f"Wayland Portal initialization failed: {error}"
            )
            if not self._ready.is_set():
                self._startup_error = translated
            elif self._error_handler is not None:
                self._error_handler(CaptureRecoverableError(str(translated)))
        finally:
            self._ready.set()

    async def _run(self, gst_launch: str) -> None:
        modules = _load_dbus_modules()
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        self._async_stop = asyncio.Event()
        try:
            self._bus = await modules.MessageBus(
                bus_type=modules.BusType.SESSION,
                negotiate_unix_fd=True,
            ).connect()
            await self._add_signal_matches(modules)
            self._bus.add_message_handler(self._handle_signal)
            self._session_handle = await self._create_session(modules)
            await self._select_sources(modules, self._session_handle)
            streams = await self._start_session(modules, self._session_handle)
            monitors = _monitors_from_streams(streams)
            for stream in streams:
                remote_fd = await self._open_pipewire_remote(
                    modules,
                    self._session_handle,
                )
                reader = _GStreamerReader(
                    executable=gst_launch,
                    remote_fd=remote_fd,
                    stream=stream,
                    frame_handler=self._on_frame,
                    error_handler=self._on_reader_error,
                    target_fps=self._target_fps,
                )
                reader.start()
                self._readers.append(reader)
            self._monitors = monitors
            self._ready.set()
            await self._async_stop.wait()
        finally:
            await self._cleanup_portal(modules)
            self._task = None
            self._loop = None
            self._async_stop = None

    async def _add_signal_matches(self, modules: Any) -> None:
        for interface, member in (
            (_REQUEST_INTERFACE, "Response"),
            (_SESSION_INTERFACE, "Closed"),
        ):
            rule = f"type='signal',interface='{interface}',member='{member}'"
            await self._call(
                modules,
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[rule],
            )

    async def _create_session(self, modules: Any) -> str:
        token = _portal_token("create")
        session_token = _portal_token("session")
        response = await self._portal_request(
            modules,
            member="CreateSession",
            signature="a{sv}",
            body=[
                {
                    "handle_token": modules.Variant("s", token),
                    "session_handle_token": modules.Variant("s", session_token),
                }
            ],
        )
        session_handle = _variant_value(response.get("session_handle"))
        if not isinstance(session_handle, str) or not session_handle.startswith("/"):
            raise CaptureUnavailableError("Portal returned an invalid session handle")
        return session_handle

    async def _select_sources(self, modules: Any, session_handle: str) -> None:
        await self._portal_request(
            modules,
            member="SelectSources",
            signature="oa{sv}",
            body=[
                session_handle,
                {
                    "handle_token": modules.Variant("s", _portal_token("select")),
                    "types": modules.Variant("u", 1),
                    "multiple": modules.Variant("b", True),
                    "cursor_mode": modules.Variant("u", 1),
                },
            ],
        )

    async def _start_session(
        self,
        modules: Any,
        session_handle: str,
    ) -> list[_PortalStream]:
        response = await self._portal_request(
            modules,
            member="Start",
            signature="osa{sv}",
            body=[
                session_handle,
                "",
                {"handle_token": modules.Variant("s", _portal_token("start"))},
            ],
        )
        return _streams_from_response(response)

    async def _portal_request(
        self,
        modules: Any,
        *,
        member: str,
        signature: str,
        body: list[Any],
    ) -> Mapping[str, Any]:
        reply = await self._call(
            modules,
            destination=_PORTAL_DESTINATION,
            path=_PORTAL_PATH,
            interface=_SCREENCAST_INTERFACE,
            member=member,
            signature=signature,
            body=body,
        )
        request_path = reply.body[0]
        loop = asyncio.get_running_loop()
        if request_path in self._responses:
            code, response = self._responses.pop(request_path)
        else:
            waiter = loop.create_future()
            self._response_waiters[request_path] = waiter
            try:
                try:
                    code, response = await asyncio.wait_for(
                        waiter,
                        timeout=self._startup_timeout,
                    )
                except TimeoutError as error:
                    raise CapturePermissionDeniedError(
                        "Wayland screen capture was not approved during "
                        f"Portal {member}"
                    ) from error
            finally:
                self._response_waiters.pop(request_path, None)
        error = _portal_response_error(member, code)
        if error is not None:
            raise error
        return response

    async def _open_pipewire_remote(self, modules: Any, session_handle: str) -> int:
        reply = await self._call(
            modules,
            destination=_PORTAL_DESTINATION,
            path=_PORTAL_PATH,
            interface=_SCREENCAST_INTERFACE,
            member="OpenPipeWireRemote",
            signature="oa{sv}",
            body=[session_handle, {}],
        )
        if not reply.body or not reply.unix_fds:
            raise CaptureUnavailableError("Portal returned no PipeWire file descriptor")
        descriptor_index = int(reply.body[0])
        try:
            return int(reply.unix_fds[descriptor_index])
        except (IndexError, TypeError, ValueError) as error:
            raise CaptureUnavailableError(
                "Portal returned an invalid PipeWire file descriptor"
            ) from error

    async def _call(
        self,
        modules: Any,
        *,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str,
        body: list[Any],
    ) -> Any:
        if self._bus is None:
            raise CaptureUnavailableError("Portal D-Bus is not connected")
        reply = await self._bus.call(
            modules.Message(
                destination=destination,
                path=path,
                interface=interface,
                member=member,
                signature=signature,
                body=body,
            )
        )
        if reply.message_type is modules.MessageType.ERROR:
            detail = str(reply.body[0]) if reply.body else "unknown D-Bus error"
            raise _portal_dbus_error(
                member,
                str(getattr(reply, "error_name", "")),
                detail,
            )
        return reply

    def _handle_signal(self, message: Any) -> bool:
        if message.interface == _REQUEST_INTERFACE and message.member == "Response":
            code = int(message.body[0])
            response = message.body[1]
            waiter = self._response_waiters.get(message.path)
            if waiter is not None and not waiter.done():
                waiter.set_result((code, response))
            else:
                self._responses[message.path] = (code, response)
            return True
        if (
            message.interface == _SESSION_INTERFACE
            and message.member == "Closed"
            and message.path == self._session_handle
        ):
            if self._ready.is_set() and self._error_handler is not None:
                self._error_handler(
                    CaptureRecoverableError("Wayland Portal session was closed")
                )
            if self._async_stop is not None:
                self._async_stop.set()
            return True
        return False

    def _on_frame(self, monitor_id: str, image: np.ndarray) -> None:
        if self._frame_handler is not None:
            self._frame_handler(monitor_id, image)

    def _on_reader_error(self, error: CaptureRecoverableError) -> None:
        if self._error_handler is not None:
            self._error_handler(error)
        loop = self._loop
        stop_event = self._async_stop
        if loop is not None and stop_event is not None:
            loop.call_soon_threadsafe(stop_event.set)

    async def _cleanup_portal(self, modules: Any) -> None:
        readers = list(self._readers)
        self._readers = []
        for reader in readers:
            reader.stop()
        if self._bus is not None and self._session_handle is not None:
            try:
                await self._call(
                    modules,
                    destination=_PORTAL_DESTINATION,
                    path=self._session_handle,
                    interface=_SESSION_INTERFACE,
                    member="Close",
                    signature="",
                    body=[],
                )
            except Exception:
                LOGGER.debug("Could not close Portal session", exc_info=True)
        self._session_handle = None
        if self._bus is not None:
            try:
                self._bus.disconnect()
            except Exception:
                LOGGER.debug("Could not disconnect Portal D-Bus", exc_info=True)
            self._bus = None


class _GStreamerReader:
    """Continuously drain one raw BGR GStreamer stream into a latest slot."""

    def __init__(
        self,
        *,
        executable: str,
        remote_fd: int,
        stream: _PortalStream,
        frame_handler: FrameHandler,
        error_handler: ErrorHandler,
        target_fps: int,
    ) -> None:
        self._executable = executable
        self._remote_fd = remote_fd
        self._stream = stream
        self._frame_handler = frame_handler
        self._error_handler = error_handler
        self._target_fps = target_fps
        self._stop = Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: Thread | None = None

    def start(self) -> None:
        command = _gstreamer_command(
            self._executable,
            self._remote_fd,
            self._stream,
            self._target_fps,
        )
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=(self._remote_fd,),
            )
        except (OSError, ValueError) as error:
            os.close(self._remote_fd)
            raise CaptureUnavailableError(
                f"Could not start GStreamer PipeWire reader: {error}"
            ) from error
        os.close(self._remote_fd)
        self._remote_fd = -1
        self._thread = Thread(
            target=self._read_frames,
            name=f"lavocado-pipewire-{self._stream.monitor_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._remote_fd >= 0:
            os.close(self._remote_fd)
            self._remote_fd = -1
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._process = None

    def _read_frames(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        size = self._stream.width * self._stream.height * 4
        try:
            while not self._stop.is_set():
                data = _read_exact(process.stdout, size)
                if data is None:
                    break
                bgrx = np.frombuffer(data, dtype=np.uint8).reshape(
                    (self._stream.height, self._stream.width, 4)
                )
                image = np.ascontiguousarray(bgrx[:, :, :3])
                self._frame_handler(self._stream.monitor_id, image)
        except (OSError, ValueError) as error:
            if not self._stop.is_set():
                self._error_handler(
                    CaptureRecoverableError(f"PipeWire frame read failed: {error}")
                )
            return
        if not self._stop.is_set():
            code = process.poll()
            self._error_handler(
                CaptureRecoverableError(
                    f"GStreamer PipeWire reader stopped unexpectedly ({code})"
                )
            )


@dataclass(frozen=True, slots=True)
class _DBusModules:
    MessageBus: Any
    BusType: Any
    Message: Any
    MessageType: Any
    Variant: Any


def _monitors_from_streams(streams: list[_PortalStream]) -> list[MonitorInfo]:
    if not streams:
        return []
    primary_index = next(
        (
            index
            for index, stream in enumerate(streams)
            if stream.left == 0 and stream.top == 0
        ),
        0,
    )
    return [
        stream.monitor(index, primary=index - 1 == primary_index)
        for index, stream in enumerate(streams, start=1)
    ]


def _gstreamer_command(
    executable: str,
    remote_fd: int,
    stream: _PortalStream,
    target_fps: int,
) -> list[str]:
    caps = (
        "video/x-raw,format=BGRx,"
        f"width={stream.width},height={stream.height},framerate={target_fps}/1"
    )
    return [
        executable,
        "-q",
        "pipewiresrc",
        f"fd={remote_fd}",
        f"path={stream.node_id}",
        "do-timestamp=true",
        "!",
        "queue",
        "max-size-buffers=1",
        "leaky=downstream",
        "!",
        "videoconvert",
        "!",
        "videoscale",
        "!",
        "videorate",
        "drop-only=true",
        "!",
        caps,
        "!",
        "fdsink",
        "fd=1",
        "sync=false",
    ]


def _load_dbus_modules() -> _DBusModules:
    try:
        from dbus_fast import BusType, Message, MessageType, Variant
        from dbus_fast.aio import MessageBus
    except (ImportError, OSError) as error:
        raise CaptureUnavailableError(
            f"D-Bus client is unavailable: {error}"
        ) from error
    return _DBusModules(MessageBus, BusType, Message, MessageType, Variant)


def _portal_token(prefix: str) -> str:
    return f"lavocado_{prefix}_{uuid.uuid4().hex}"


def _portal_response_error(member: str, code: int) -> CaptureError | None:
    if code == 0:
        return None
    if code == 1:
        return CapturePermissionDeniedError(
            f"Wayland screen capture was cancelled during Portal {member}"
        )
    return CaptureUnavailableError(f"Portal {member} failed with response {code}")


def _portal_dbus_error(member: str, name: str, detail: str) -> CaptureError:
    normalized = f"{name} {detail}".casefold()
    permission_markers = (
        "accessdenied",
        "notallowed",
        "permissiondenied",
        "permission denied",
    )
    if any(marker in normalized for marker in permission_markers):
        return CapturePermissionDeniedError(
            f"Wayland screen capture permission denied during Portal {member}"
        )
    return CaptureUnavailableError(f"Portal {member} failed: {detail}")


def _variant_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _pair(value: Any, name: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CaptureUnavailableError(f"Portal returned invalid stream {name}")
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError) as error:
        raise CaptureUnavailableError(
            f"Portal returned invalid stream {name}"
        ) from error


def _streams_from_response(response: Mapping[str, Any]) -> list[_PortalStream]:
    raw_streams = _variant_value(response.get("streams"))
    if not isinstance(raw_streams, (list, tuple)) or not raw_streams:
        raise CaptureUnavailableError("Portal returned no PipeWire streams")

    streams: list[_PortalStream] = []
    for raw_stream in raw_streams:
        if not isinstance(raw_stream, (list, tuple)) or len(raw_stream) != 2:
            raise CaptureUnavailableError("Portal returned invalid stream metadata")
        node_id = int(raw_stream[0])
        properties = _variant_value(raw_stream[1])
        if not isinstance(properties, Mapping):
            raise CaptureUnavailableError("Portal returned invalid stream properties")
        position = _pair(_variant_value(properties.get("position")), "position")
        size = _pair(_variant_value(properties.get("size")), "size")
        if size[0] <= 0 or size[1] <= 0:
            raise CaptureUnavailableError("Portal returned an invalid stream size")
        opaque_id = _variant_value(properties.get("id"))
        monitor_id = str(opaque_id) if opaque_id else str(node_id)
        streams.append(
            _PortalStream(
                monitor_id=monitor_id,
                node_id=node_id,
                left=position[0],
                top=position[1],
                width=size[0],
                height=size[1],
            )
        )
    return streams


def _read_exact(stream: Any, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
