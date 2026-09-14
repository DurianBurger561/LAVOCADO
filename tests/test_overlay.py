"""Tests for safe overlay dismissal."""

import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.intervention.sequence import InterventionSequence, InterventionStep
from app.platforms.capture import MonitorInfo
from app.ui.overlay import create_overlay_backend
from app.ui.overlay.macos_process_backend import MacOSProcessOverlayBackend
from app.ui.overlay.tk_backend import TkOverlayBackend, tk_geometry


class FakeRoot:
    def __init__(self) -> None:
        self.destroy_count = 0
        self.focus_count = 0
        self.quit_count = 0
        self.withdraw_count = 0
        self.scheduled: list[tuple[object, object]] = []
        self._w = "."
        self.tk = FakeTk()

    def destroy(self) -> None:
        self.destroy_count += 1

    def quit(self) -> None:
        self.quit_count += 1

    def withdraw(self) -> None:
        self.withdraw_count += 1

    def after(self, delay_ms: int, callback: object) -> None:
        self.scheduled.append((delay_ms, callback))

    def after_idle(self, callback: object) -> None:
        self.scheduled.append(("idle", callback))

    def lift(self) -> None:
        pass

    def focus_force(self) -> None:
        self.focus_count += 1


class FakeTk:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def call(self, *args: object) -> None:
        self.calls.append(args)


class FakeWidget:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}
        self.focus_count = 0

    def configure(self, **options: object) -> None:
        self.options.update(options)

    def focus_set(self) -> None:
        self.focus_count += 1


class OverlayTests(unittest.TestCase):
    def test_factory_selects_supported_backends(self) -> None:
        self.assertIsInstance(create_overlay_backend("Windows"), TkOverlayBackend)
        self.assertIsInstance(
            create_overlay_backend("Darwin"), MacOSProcessOverlayBackend
        )
        with self.assertRaises(ValueError):
            create_overlay_backend("Linux")

    def test_tk_window_uses_passed_monitor_without_display_discovery(self) -> None:
        monitor = MonitorInfo("secondary", 2, -1200, 50, 1200, 900)
        root = Mock()
        widget = Mock()
        tkinter = SimpleNamespace(
            Tk=Mock(return_value=root),
            Frame=Mock(return_value=widget),
            Label=Mock(return_value=widget),
            Button=Mock(return_value=widget),
        )

        with patch.dict("sys.modules", {"tkinter": tkinter}):
            TkOverlayBackend("Windows").show(monitor)

        root.geometry.assert_called_once_with("1200x900-1200+50")

    def test_macos_overlay_uses_an_isolated_process(self) -> None:
        overlay = MacOSProcessOverlayBackend()
        monitor = MonitorInfo("secondary", 2, -1200, 0, 1200, 900)

        with patch("app.ui.overlay.macos_process_backend.show_overlay_process") as show_process:
            overlay.show(monitor)

        show_process.assert_called_once_with(
            monitor, stop_event=overlay._stop_event
        )
        self.assertFalse(overlay.is_visible)

    def test_macos_backend_hide_requests_child_shutdown(self) -> None:
        overlay = MacOSProcessOverlayBackend()

        overlay.hide()

        self.assertTrue(overlay._stop_event.is_set())

    def test_dismiss_destroys_the_window(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        overlay._root = root

        overlay.dismiss()

        self.assertEqual(root.destroy_count, 0)
        self.assertEqual(root.scheduled[0][0], 0)
        root.scheduled[0][1]()
        self.assertEqual(root.withdraw_count, 1)
        self.assertEqual(root.quit_count, 1)
        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_dismiss_only_schedules_once(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        overlay._root = root

        overlay.dismiss()
        overlay.dismiss()

        self.assertEqual(len(root.scheduled), 1)

    def test_tk_geometry_uses_canonical_monitor_offsets(self) -> None:
        monitor = MonitorInfo("secondary", 2, -1200, 50, 1200, 900)

        self.assertEqual(tk_geometry(monitor), "1200x900-1200+50")

    def test_overlay_closes_when_parent_process_disappears(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        parent_closed = Event()
        parent_closed.set()
        overlay._root = root

        overlay._watch_parent_process(root, parent_closed)
        root.scheduled[0][1]()

        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_overlay_heartbeat_runs_on_tk_event_loop(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        heartbeat_calls: list[bool] = []
        overlay._root = root

        overlay._send_heartbeat(root, lambda: heartbeat_calls.append(True))

        self.assertEqual(heartbeat_calls, [True])
        self.assertEqual(root.scheduled[0][0], 1000)

    def test_macos_bring_to_front_does_not_force_focus(self) -> None:
        overlay = TkOverlayBackend("Darwin")
        root = FakeRoot()
        button = FakeWidget()
        overlay._root = root

        overlay._bring_to_front(button)

        self.assertEqual(root.focus_count, 0)
        self.assertEqual(button.focus_count, 0)

    def test_escape_uses_the_same_dismiss_path(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        overlay._root = root

        result = overlay._dismiss_from_event(object())

        self.assertEqual(result, "break")
        root.scheduled[0][1]()
        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_guided_dismiss_is_locked_until_final_step(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        overlay._root = root
        overlay._sequence = InterventionSequence(
            (
                InterventionStep("pause", "Pause", "Pause", "Wait", 1.0),
                InterventionStep(
                    "ready",
                    "Ready",
                    "Ready",
                    "Continue",
                    None,
                    True,
                ),
            )
        )

        self.assertFalse(overlay.request_dismiss())
        self.assertEqual(root.destroy_count, 0)

        overlay._sequence.advance()

        self.assertTrue(overlay.request_dismiss())
        root.scheduled[0][1]()
        self.assertEqual(root.destroy_count, 1)

    def test_render_schedules_each_stage_and_enables_final_button(self) -> None:
        overlay = TkOverlayBackend("Windows")
        root = FakeRoot()
        title = FakeWidget()
        body = FakeWidget()
        button = FakeWidget()
        overlay._root = root
        overlay._sequence = InterventionSequence(
            (
                InterventionStep("pause", "Pause", "Pause body", "Wait", 1.0),
                InterventionStep("breathe", "Breathe", "Breathe body", "Wait", 2.0),
                InterventionStep(
                    "ready",
                    "Ready",
                    "Ready body",
                    "Continue",
                    None,
                    True,
                ),
            )
        )

        overlay._render_step(title, body, button)
        self.assertEqual(title.options["text"], "Pause")
        self.assertEqual(button.options["state"], "disabled")
        self.assertEqual(root.scheduled[0][0], 1000)

        root.scheduled[0][1]()
        self.assertEqual(title.options["text"], "Breathe")
        self.assertEqual(root.scheduled[1][0], 2000)

        root.scheduled[1][1]()
        self.assertEqual(title.options["text"], "Ready")
        self.assertEqual(body.options["text"], "Ready body")
        self.assertEqual(button.options["text"], "Continue")
        self.assertEqual(button.options["state"], "normal")
        self.assertEqual(button.focus_count, 1)

if __name__ == "__main__":
    unittest.main()
