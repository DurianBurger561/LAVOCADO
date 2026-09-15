"""Exercise the real macOS overlay with Cocoa events and an offline client.

Run manually on a logged-in Mac: python scripts/verify_overlay_input.py
The test window closes itself and never loads the user's API key or history.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.intervention.llm import LLMClient
from app.intervention.sequence import default_intervention_sequence
from app.platforms.capture import MonitorInfo
from app.ui.overlay.tk_backend import TkOverlayBackend


def verify(width: int, height: int, screenshot: Path | None, exit_mode: str, guided: bool, language: str) -> None:
    import AppKit
    import Quartz

    def ready_sequence():
        sequence = default_intervention_sequence()
        if not guided:
            while sequence.advance():
                pass
        return sequence

    application = None
    failures: list[Exception] = []
    finished = False
    started = False

    def post_key(window, text: str, code: int) -> None:
        for event_type in (AppKit.NSEventTypeKeyDown, AppKit.NSEventTypeKeyUp):
            event = AppKit.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
                event_type, (0, 0), 0, time.monotonic(), window.windowNumber(),
                None, text, text, False, code,
            )
            application.postEvent_atStart_(event, False)

    def click(window, root, widget) -> None:
        point = (
            widget.winfo_rootx() + widget.winfo_width() / 2,
            widget.winfo_rooty() + widget.winfo_height() / 2,
        )
        # Tk hit-tests using the current pointer, not an NSEvent's location.
        Quartz.CGWarpMouseCursorPosition(point)
        local = (point[0] - root.winfo_rootx(), root.winfo_height() - (point[1] - root.winfo_rooty()))
        for event_type in (AppKit.NSEventTypeMouseMoved, AppKit.NSEventTypeLeftMouseDown, AppKit.NSEventTypeLeftMouseUp):
            event = AppKit.NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
                event_type, local, 0, time.monotonic(), window.windowNumber(),
                None, 1, 1, 1.0,
            )
            application.postEvent_atStart_(event, False)

    def steps():
        nonlocal finished, application
        root = backend._root
        stages = set()
        while backend._ai_panel is None:
            stages.add(backend._sequence.current.name)
            yield 100
        panel = backend._ai_panel
        application = AppKit.NSApplication.sharedApplication()
        if guided:
            assert {'pause', 'breathe'} <= stages, f'Missing intervention stages: {stages}'
            assert backend._sequence.current.name == 'ready'
            print('PASS Pause -> Breathe -> AI / Continue transition', flush=True)
        while panel._entry.cget('state') == 'disabled':
            yield 50
        yield 300
        window = next(w for w in application.windows() if w.title() == root.title())
        assert window.canBecomeKeyWindow(), 'Overlay rejects keyboard activation'
        assert window.isKeyWindow(), 'Overlay is not the key window'
        assert window.styleMask() == AppKit.NSWindowStyleMaskBorderless, 'Title bar returned'
        required = (
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | getattr(AppKit, 'NSWindowCollectionBehaviorCanJoinAllApplications', 0)
        )
        assert window.collectionBehavior() & required == required, f'Spaces flags lost: {window.collectionBehavior():x} (expected {required:x})'
        entry = panel._entry
        assert root.focus_get() == entry, 'Entry did not receive Tk focus'
        assert entry.winfo_height() >= 32, 'Entry height collapsed'
        entry_bottom = entry.winfo_rooty() + entry.winfo_height()
        panel_bottom = panel._frame.winfo_rooty() + panel._frame.winfo_height()
        for action in (panel._start_button, panel._send_button, panel._exit_button):
            button = action._label
            assert button.winfo_height() >= button.winfo_reqheight(), 'Button clipped'
            assert button.winfo_rooty() >= entry_bottom, 'Input overlaps button'
            assert button.winfo_rooty() + button.winfo_height() <= panel_bottom
        assert backend._main_container.winfo_rooty() >= panel_bottom
        assert backend._main_container.winfo_rooty() + backend._main_container.winfo_height() <= root.winfo_rooty() + root.winfo_height(), 'Continue button outside screen'
        print('PASS keyboard activation, borderless window, Spaces flags and layout', flush=True)

        click(window, root, entry)
        yield 100
        for char, code in (('a', 0), ('b', 11), ('c', 8)):
            post_key(window, char, code)
        yield 150
        assert entry.get() == 'abc', f'Native key events did not enter text: {entry.get()!r}'
        post_key(window, '\x7f', 51)
        yield 100
        assert entry.get() == 'ab', 'Backspace failed'

        # Exercise the same NSTextInputClient callbacks used by macOS IMEs,
        # including temporary marked text followed by a Chinese commit.
        view = window.contentView()
        view.setMarkedText_selectedRange_replacementRange_('nihao', (5, 0), (AppKit.NSNotFound, 0))
        yield 100
        view.insertText_replacementRange_('\u4f60\u597d', (AppKit.NSNotFound, 0))
        yield 100
        expected = 'ab\u4f60\u597d'
        assert entry.get() == expected, f'Chinese text commit failed: {entry.get()!r}'
        if screenshot is not None:
            rep = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
            view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), rep)
            assert rep.representationUsingType_properties_(
                AppKit.NSBitmapImageFileTypePNG, {}
            ).writeToFile_atomically_(str(screenshot), True)
        post_key(window, '\r', 36)
        yield 200
        assert backend.is_visible, 'Enter dismissed overlay instead of submitting'
        assert ('user', expected) in panel._conversation, 'Enter did not submit the reply'
        assert entry.get() == '', 'Submitted text not cleared'
        print('PASS Cocoa keystrokes, Backspace, Chinese composition and Enter submission', flush=True)

        click(window, root, panel._start_button._label)
        yield 200
        while panel._entry.cget('state') == 'disabled':
            yield 50
        assert panel._phase == 'practice', 'Start button failed'
        post_key(window, 'a', 0)
        yield 100
        click(window, root, panel._send_button._label)
        yield 200
        while panel._entry.cget('state') == 'disabled':
            yield 50
        assert ('user', 'a') in panel._history, 'Send button failed'
        assert panel._round_index == 1
        print('PASS Start and Send mouse clicks', flush=True)
        finished = True
        if exit_mode == 'escape':
            post_key(window, '\x1b', 53)
        elif exit_mode == 'exit':
            click(window, root, backend._exit_button._label)
        else:
            dismiss = next(
                child for child in backend._main_container.winfo_children()
                if child.cget('text') == backend._sequence.current.button_label
            )
            click(window, root, dismiss)

    def advance() -> None:
        try:
            delay = next(checks)
        except StopIteration:
            return
        except Exception as error:
            failures.append(error)
            backend.dismiss()
        else:
            backend._root.after(delay, advance)

    def heartbeat() -> None:
        nonlocal started
        if started:
            return
        started = True
        backend._root.after(0, advance)
        backend._root.after(20000, timeout)

    def timeout() -> None:
        failures.append(AssertionError('Overlay input test or dismissal timed out'))
        backend.dismiss()

    with TemporaryDirectory(prefix='lavocado-input-test-') as data_dir, patch(
        'app.ui.overlay.ai_panel.LLMClient.from_environment', return_value=LLMClient(language=language)
    ):
        backend = TkOverlayBackend('Darwin', ready_sequence, Path(data_dir))
        checks = steps()
        backend.show(
            MonitorInfo('input-test', 1, 0, 0, width, height),
            heartbeat_callback=heartbeat,
        )
    if failures:
        raise failures[0]
    assert finished, 'Test window closed before verification completed'
    assert not backend.is_visible
    print(f'PASS {exit_mode} dismissal; verified {width}x{height}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width', type=int, default=1398)
    parser.add_argument('--height', type=int, default=924)
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--exit-mode', choices=('escape', 'exit', 'continue'), default='escape')
    parser.add_argument('--guided', action='store_true')
    parser.add_argument('--language', choices=('zh', 'en'), default='zh')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This native GUI check requires macOS')
    verify(args.width, args.height, args.screenshot, args.exit_mode, args.guided, args.language)
