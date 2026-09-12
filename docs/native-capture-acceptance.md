# Native capture acceptance checklist

This checklist maps the native-capture implementation to automated evidence
and identifies the checks that still require physical Windows, macOS, and Linux
desktop sessions. Captured pixels remain in process memory and must not be
attached to test reports.

## Automated acceptance

| Requirement | Implementation | Automated evidence |
| --- | --- | --- |
| Shared capture contract | `app/platforms/capture/base.py` and `models.py` | `test_capture_backends.py`, `test_capture.py` |
| Windows native capture | DXGI adapter duplication with latest-frame semantics | `test_windows_dxgi_capture.py` |
| macOS native capture | ScreenCaptureKit streams and normalized dirty rectangles | `test_macos_screencapturekit.py` |
| Wayland and WSLg | PipeWire portal routing with explicit permission denial | `test_linux_portal.py`, `test_linux_session.py`, `test_validate_linux_capture.py` |
| Linux X11 | XShm backend and session routing | `test_linux_xshm.py`, `test_linux_session.py` |
| Global fallback | One-way native-to-MSS fallback with a recorded reason | `test_capture_backends.py` |
| Permission policy | User denial stops capture instead of bypassing through MSS | platform backend tests |
| Freshness and bounded buffering | Monotonic sequences and latest-frame slots | platform backend tests and `test_sequence.py` |
| Per-monitor change scheduling | Native changed regions, bounded software grayscale fallback, periodic scan, and candidate follow-up | `test_change_scheduler.py`, `test_service.py` |
| Capture diagnostics | Active/preferred backend, fallback reason, frame age, health, and monitor count | `test_diagnostics.py`, `test_service.py` |
| Developer override | Auto, native-only, and MSS-only; packaged builds remain Auto | `test_capture_override.py` |
| Privacy | No pixel data in diagnostics, benchmark summaries, or soak output | diagnostics, benchmark, and soak tests |
| Packaging routes | Platform-specific dependencies and build jobs | GitHub Actions test and package workflows |

Run the complete automated gate from the repository root:

```bash
python -m compileall -q app scripts tests main.py
python scripts/validate_linux_capture.py --self-check
python -m unittest discover -s tests -v
```

The Linux routing self-check is meaningful on every OS because it supplies a
controlled environment map. A live Linux capture validation still requires an
actual Linux desktop session.

## Required physical-platform validation

Automated CI cannot validate desktop permission prompts, GPU/display drivers,
Retina or DPI scaling, lock and sleep transitions, or monitor hot-plug. Before
release, complete these checks on real systems:

| Platform | Native path | Fallback path | Required scenarios |
| --- | --- | --- | --- |
| Windows 10/11 | DXGI Desktop Duplication | MSS | One and multiple monitors, mixed DPI, fullscreen, lock/unlock, sleep/resume, hot-plug |
| macOS 13+ Intel/Apple Silicon | ScreenCaptureKit | MSS for technical failure only | Permission grant and denial, Retina scaling, fullscreen, sleep/resume, hot-plug |
| GNOME/KDE Wayland | PipeWire portal | MSS for technical failure only | Select all displays, cancel permission, fullscreen, sleep/resume, hot-plug |
| Linux X11/Xorg | XShm | MSS | One and multiple monitors, fullscreen, lock/unlock, hot-plug |
| WSLg | PipeWire portal when available | MSS | One and multiple monitors and a recorded native-unavailable reason |

For Linux, follow `docs/linux-capture-validation.md`. For long-run checks,
follow `docs/capture-soak-testing.md` and run at least the one-hour Auto,
native-only, and MSS-only matrix. The eight-hour Auto run is recommended for a
release candidate.

## Release decision

Code-level acceptance is complete when the full automated gate passes. Release
acceptance is complete only after the applicable physical-platform rows and
one-hour soak runs are recorded without stale frames, unbounded memory/resource
growth, incorrect monitor selection, or a permission-denial bypass.
