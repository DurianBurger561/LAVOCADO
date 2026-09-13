"""Delayed application selection publishes only a stable identifier."""

import unittest

from app.context.models import ApplicationContext
from app.ui.app_picker import ForegroundAppPicker


class FakeTimer:
    def __init__(self, seconds, callback) -> None:
        self.seconds = seconds
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self.callback()


class AppPickerTests(unittest.TestCase):
    def test_selects_only_identifier_after_delay(self) -> None:
        timers = []

        def timer_factory(seconds, callback):
            timer = FakeTimer(seconds, callback)
            timers.append(timer)
            return timer

        def read_application():
            return ApplicationContext(
                " Chrome.EXE ", "Private Window Title", "chrome.exe", "123", 0.0,
                process_id=42,
            )

        picker = ForegroundAppPicker(
            read_application, timer_factory=timer_factory
        )
        self.assertEqual(picker.begin()["status"], "pending")
        self.assertEqual(picker.begin()["status"], "pending")
        self.assertEqual(len(timers), 1)
        self.assertEqual(timers[0].seconds, 4.0)
        self.assertTrue(timers[0].started)
        self.assertTrue(timers[0].daemon)
        self.assertEqual(picker.result()["identifier"], None)

        timers[0].fire()

        self.assertEqual(picker.result()["status"], "ready")
        self.assertEqual(picker.result()["identifier"], "chrome.exe")
        self.assertNotIn("Private", str(picker.result()))
        self.assertNotIn("42", str(picker.result()))

        self.assertEqual(picker.begin()["status"], "pending")
        self.assertEqual(len(timers), 2)

    def test_unavailable_identity_and_reader_error_do_not_escape(self) -> None:
        timers = []

        def timer_factory(seconds, callback):
            timer = FakeTimer(seconds, callback)
            timers.append(timer)
            return timer

        def broken_reader():
            raise PermissionError("private window title")

        picker = ForegroundAppPicker(broken_reader, timer_factory=timer_factory)
        picker.begin()
        timers[0].fire()

        self.assertEqual(picker.result()["status"], "unavailable")
        self.assertNotIn("private", str(picker.result()))

    def test_close_cancels_pending_sample_and_disallows_restart(self) -> None:
        timers = []

        def timer_factory(seconds, callback):
            timer = FakeTimer(seconds, callback)
            timers.append(timer)
            return timer

        picker = ForegroundAppPicker(lambda: None, timer_factory=timer_factory)
        picker.begin()
        picker.close()

        self.assertTrue(timers[0].cancelled)
        timers[0].fire()
        self.assertEqual(picker.result()["status"], "idle")
        self.assertEqual(picker.begin()["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
