"""Tests for safe overlay dismissal."""

import unittest

from app.intervention.sequence import InterventionSequence, InterventionStep
from app.vision.overlay import Overlay


class FakeRoot:
    def __init__(self) -> None:
        self.destroy_count = 0
        self.scheduled: list[tuple[int, object]] = []

    def destroy(self) -> None:
        self.destroy_count += 1

    def after(self, delay_ms: int, callback: object) -> None:
        self.scheduled.append((delay_ms, callback))

    def lift(self) -> None:
        pass

    def focus_force(self) -> None:
        pass


class FakeWidget:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}
        self.focus_count = 0

    def configure(self, **options: object) -> None:
        self.options.update(options)

    def focus_set(self) -> None:
        self.focus_count += 1


class OverlayTests(unittest.TestCase):
    def test_dismiss_destroys_the_window(self) -> None:
        overlay = Overlay()
        root = FakeRoot()
        overlay._root = root

        overlay.dismiss()

        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_escape_uses_the_same_dismiss_path(self) -> None:
        overlay = Overlay()
        root = FakeRoot()
        overlay._root = root

        result = overlay._dismiss_from_event(object())

        self.assertEqual(result, "break")
        self.assertEqual(root.destroy_count, 1)
        self.assertFalse(overlay.is_visible)

    def test_guided_dismiss_is_locked_until_final_step(self) -> None:
        overlay = Overlay()
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
        self.assertEqual(root.destroy_count, 1)

    def test_render_schedules_each_stage_and_enables_final_button(self) -> None:
        overlay = Overlay()
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
