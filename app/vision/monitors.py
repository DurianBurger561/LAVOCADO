"""Utilities for choosing a monitor consistently across displays."""

from collections.abc import Mapping, Sequence

Monitor = Mapping[str, object]


def select_monitor_index(
    monitors: Sequence[Monitor],
    preferred_index: int | None = None,
) -> int:
    """Return the preferred or most likely primary physical monitor index."""

    if len(monitors) < 2:
        raise RuntimeError("No physical monitor is available")

    if preferred_index is not None:
        if not 0 < preferred_index < len(monitors):
            raise ValueError(
                f"Monitor {preferred_index} is unavailable. "
                f"Found {len(monitors) - 1} monitor(s)."
            )
        return preferred_index

    for index, monitor in enumerate(monitors[1:], start=1):
        if monitor.get("is_primary") is True:
            return index

    # Some capture backends omit a primary flag; the origin is a useful fallback.
    for index, monitor in enumerate(monitors[1:], start=1):
        if _coordinate(monitor, "left") == 0 and _coordinate(monitor, "top") == 0:
            return index

    return 1


def monitor_geometry(monitor: Monitor) -> str:
    """Convert an MSS monitor mapping into Tk's WIDTHxHEIGHT+X+Y format."""

    left = _coordinate(monitor, "left")
    top = _coordinate(monitor, "top")
    width = _coordinate(monitor, "width")
    height = _coordinate(monitor, "height")

    if width < 1 or height < 1:
        raise ValueError("Monitor width and height must be positive")

    return f"{width}x{height}{_signed(left)}{_signed(top)}"


def monitor_index_at_point(
    monitors: Sequence[Monitor],
    x: int,
    y: int,
) -> int | None:
    """Return the physical monitor containing a virtual-desktop point."""

    for index, monitor in enumerate(monitors[1:], start=1):
        left = _coordinate(monitor, "left")
        top = _coordinate(monitor, "top")
        width = _coordinate(monitor, "width")
        height = _coordinate(monitor, "height")
        if left <= x < left + width and top <= y < top + height:
            return index
    return None


def _coordinate(monitor: Monitor, name: str) -> int:
    value = monitor.get(name)
    if not isinstance(value, int):
        raise TypeError(f"Monitor {name} must be an integer")
    return value


def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)
