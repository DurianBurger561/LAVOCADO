# Linux capture validation

This checklist validates capture metadata and live in-memory frames. The tool
does not save screenshots, serialize pixels, or upload captured content.

## Automated routing check

Run this on any supported development system:

```bash
python scripts/validate_linux_capture.py --self-check
```

The four expected routes are:

| Case | Route | Preferred backend |
| --- | --- | --- |
| Wayland | `pipewire_portal` | `linux_pipewire_portal` |
| X11 | `xshm` | `linux_xshm` |
| WSLg | `pipewire_portal` | `linux_pipewire_portal` |
| Headless/unknown | `mss` | `mss` |

GitHub Actions runs this check on the Linux test job.

## Live validation

Install the Linux runtime packages listed in the main README, activate the
virtual environment, and run:

```bash
python scripts/validate_linux_capture.py
```

The command requests two fresh frames from every selected monitor. It validates
that each frame:

- is a C-contiguous `uint8` BGR array;
- matches the monitor dimensions;
- has a sequence greater than the preceding frame;
- identifies the backend that actually supplied it.

A successful result has `ok: true`, a healthy capture status, and
`frames_saved: false` plus `frames_uploaded: false`.

## Manual matrix

Run the live command once for each available environment:

| Environment | Action | Expected result |
| --- | --- | --- |
| GNOME Wayland | Approve all requested displays | Active backend is `linux_pipewire_portal` |
| KDE Wayland | Approve all requested displays | Active backend is `linux_pipewire_portal` |
| Wayland permission test | Cancel the system picker | Exit code 2 and `permission_denied`; MSS does not start |
| X11/Xorg | Run from an X11 session | Active backend is `linux_xshm` |
| WSLg | Run with the normal WSLg environment | Portal is preferred; technical unavailability may report MSS fallback |
| Single display | Select the only display | `monitor_count` is 1 and both sequences advance |
| Multiple displays | Select every display | `monitor_count` matches the selection and every sequence advances |

Backend forcing and deterministic native-failure simulation are introduced by
the later developer-override phase. Until then, a naturally unavailable native
component may be used to confirm that `active_backend` becomes `mss` and
`fallback_reason` is populated.

## Result handling

The JSON is safe to attach to a bug report. Do not add screenshots or captured
pixel dumps. For a failure, retain:

- Linux distribution and desktop version;
- X11, Wayland, or WSLg session type;
- `preferred_backend`, `active_backend`, and `fallback_reason`;
- monitor count and the reported exception type;
- whether the problem followed lock/unlock, suspend/resume, or display hotplug.
