"""Tests for safe overlay dismissal."""

import unittest
from concurrent.futures import Future
from threading import Event
from unittest.mock import patch

from app.intervention.sequence import InterventionSequence, InterventionStep
from app.vision.overlay import Overlay


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


class FakePlatform:
    def __init__(self, name: str = "Test") -> None:
        self.name = name
        self.prepared_roots: list[object] = []
        self.release_focus_count = 0

    @staticmethod
    def tkinter_help() -> str:
        return "test Tkinter help"

    def release_overlay_focus(self) -> None:
        self.release_focus_count += 1

    def prepare_overlay_window(self, root: object) -> None:
        self.prepared_roots.append(root)


class OverlayTests(unittest.TestCase):
    def test_macos_overlay_uses_an_isolated_process(self) -> None:
        overlay = Overlay(FakePlatform(name="Darwin"))
        message: Future[str] = Future()

        with patch("app.vision.overlay_process.show_overlay_process") as show_process:
            overlay.show(monitor_index=2, support_message=message)

        show_process.assert_called_once_with(2, message)
        self.assertFalse(overlay.is_visible)

    def test_dismiss_destroys_the_window(self) -> None:
        overlay = Overlay(FakePlatform())
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
        overlay = Overlay(FakePlatform())
        root = FakeRoot()
        overlay._root = root

        overlay.dismiss()
        overlay.dismiss()

        self.assertEqual(len(root.scheduled), 1)

    def test_cleanup_releases_overlay_focus(self) -> None:
        platform = FakePlatform()
        overlay = Overlay(platform)

        overlay._release_overlay_focus()

        self.assertEqual(platform.release_focus_count, 1)

    def test_overlay_closes_when_parent_process_disappears(self) -> None:
        overlay = Overlay(FakePlatform())
        root = FakeRoot()
        parent_closed = Event()
        parent_closed.set()
        overlay._root = root

        overlay._watch_parent_process(root, parent_closed)
        root.scheduled[0][1]()

        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_overlay_heartbeat_runs_on_tk_event_loop(self) -> None:
        overlay = Overlay(FakePlatform())
        root = FakeRoot()
        heartbeat_calls: list[bool] = []
        overlay._root = root

        overlay._send_heartbeat(root, lambda: heartbeat_calls.append(True))

        self.assertEqual(heartbeat_calls, [True])
        self.assertEqual(root.scheduled[0][0], 1000)

    def test_overlay_delegates_platform_window_preparation(self) -> None:
        platform = FakePlatform()
        overlay = Overlay(platform)
        root = FakeRoot()

        overlay._prepare_overlay_window(root)

        self.assertEqual(platform.prepared_roots, [root])

    def test_macos_bring_to_front_does_not_force_focus(self) -> None:
        overlay = Overlay(FakePlatform(name="Darwin"))
        root = FakeRoot()
        button = FakeWidget()
        overlay._root = root

        overlay._bring_to_front(button)

        self.assertEqual(root.focus_count, 0)
        self.assertEqual(button.focus_count, 0)

    def test_escape_uses_the_same_dismiss_path(self) -> None:
        overlay = Overlay(FakePlatform())
        root = FakeRoot()
        overlay._root = root

        result = overlay._dismiss_from_event(object())

        self.assertEqual(result, "break")
        root.scheduled[0][1]()
        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_guided_dismiss_is_locked_until_final_step(self) -> None:
        overlay = Overlay(FakePlatform())
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
        overlay = Overlay(FakePlatform())
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

    def test_ready_stage_displays_completed_support_message(self) -> None:
        overlay = Overlay(FakePlatform())
        root = FakeRoot()
        body = FakeWidget()
        message: Future[str] = Future()
        message.set_result("Take a short walk away from the screen.")
        overlay._root = root
        overlay._support_message = message

        overlay._show_support_message(body)

        self.assertEqual(
            body.options["text"],
            "Take a short walk away from the screen.",
        )


if __name__ == "__main__":
    unittest.main()
