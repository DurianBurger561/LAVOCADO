# Native capture acceptance checklist

This checklist maps the native-capture implementation to automated evidence
and identifies the checks that still require physical Windows and macOS
desktop sessions. Captured pixels remain in process memory and must not be
attached to test reports.

## Automated acceptance

| Requirement | Implementation | Automated evidence |
| --- | --- | --- |
| Shared capture contract | `app/platforms/capture/base.py` and `models.py` | `test_capture_backends.py` |
| Windows native capture | DXGI adapter duplication with latest-frame semantics | `test_windows_dxgi_capture.py` |
| macOS native capture | ScreenCaptureKit streams and normalized dirty rectangles | `test_macos_screencapturekit.py` |
| Global fallback | One-way native-to-MSS fallback with a recorded reason | `test_capture_backends.py` |
| Permission policy | User denial stops capture instead of bypassing through MSS | platform backend tests |
| Freshness and bounded buffering | Monotonic sequences and latest-frame slots | platform backend tests and `test_sequence.py` |
| Per-monitor change scheduling | Native changed regions, bounded software grayscale fallback, periodic scan, and candidate follow-up | `test_change_scheduler.py`, `test_service.py` |
| Capture diagnostics | Active/preferred backend, fallback reason, frame age, health, and monitor count | `test_diagnostics.py`, `test_service.py` |
| Developer override | Auto, native-only, and MSS-only; packaged builds remain Auto | `test_capture_override.py` |
| Privacy | No pixel data in diagnostics | `test_diagnostics.py` |
| Packaging routes | Platform-specific dependencies and build jobs | GitHub Actions test and package workflows |

Run the complete automated gate from the repository root:

```bash
python -m compileall -q app lavocado_packaging scripts tests main.py
python -m unittest discover -s tests -v
```

## Required physical-platform validation

Automated CI cannot validate desktop permission prompts, GPU/display drivers,
Retina or DPI scaling, lock and sleep transitions, or monitor hot-plug. Before
release, complete these checks on real systems:

| Platform | Native path | Fallback path | Required scenarios |
| --- | --- | --- | --- |
| Windows 10/11 | DXGI Desktop Duplication | MSS | One and multiple monitors, mixed DPI, fullscreen, lock/unlock, sleep/resume, hot-plug |
| macOS 13+ Intel/Apple Silicon | ScreenCaptureKit | MSS for technical failure only | Permission grant and denial, Retina scaling, fullscreen, sleep/resume, hot-plug |

For long-run checks, manually exercise Auto, native-only, and MSS-only capture
on physical displays and record resource usage and capture health.

## Release decision

Code-level acceptance is complete when the full automated gate passes. Release
acceptance is complete only after the applicable physical-platform rows and
stability checks are recorded without stale frames, unbounded memory/resource
growth, incorrect monitor selection, or a permission-denial bypass.
