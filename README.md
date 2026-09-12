<p align="center">
  <img src="assets/神秘牛油果.png" length="300" width="300" alt="LAVOCADO logo">
</p>

<h1 align="center">LAVOCADO / 小油果</h1>

<p align="center"><a href="README.md"><b>🇬🇧🇺🇸🇨🇦🇦🇺🇳🇿English<b></a> | <a href="README.zh.md"><b>🇨🇳中文<b></a></p>

LAVOCADO is a local-first desktop protection tool. It monitors each connected
display independently, confirms visual risk across multiple frames, and covers
only the display that triggered protection.

Screenshots are processed locally and are not stored or sent to an LLM.
The primary whole-screen detector uses NudeNet 640m at 640-pixel inference.
The full-resolution capture remains only in memory for later local rechecks.

When a risk is confirmed, the affected display moves through a short pause,
one guided breath, and a ready stage before enabling the continue button.
`Esc` remains available as an emergency exit.

## Local data and privacy

When protection is triggered, LAVOCADO stores only the UTC time, detector
label, confidence, monitor number, and whether the intervention was shown. It
does not store screenshots, URLs, or window titles.

The SQLite event database is stored in the current user's application-data
directory:

- Windows: `%LOCALAPPDATA%\\LAVOCADO\\events.db`
- macOS: `~/Library/Application Support/LAVOCADO/events.db`
- Linux or WSL: `${XDG_DATA_HOME:-~/.local/share}/lavocado/events.db`

Set `LAVOCADO_DATA_DIR` before starting the app to use a different directory.

## Optional AI support message

LAVOCADO works without an API key and uses a built-in local message by default.
To enable a short AI-generated message in the final intervention stage, set an
OpenAI API key before starting the application:

```powershell
# Windows PowerShell
$env:OPENAI_API_KEY="your-api-key"
```

```bash
# macOS, Linux, or WSL
export OPENAI_API_KEY="your-api-key"
```

Only a fixed request for a supportive message is sent. Screenshots, detector
labels, confidence values, monitor numbers, URLs, and window titles are never
included. API response storage is disabled for this request. Set
`LAVOCADO_OPENAI_MODEL` to override the default model.

## Foreground-window blocklist

Add case-insensitive application or title terms in `app/config.py`:

```python
BLOCKED_APPS = ["Steam", "reddit.com"]
```

When a term matches, LAVOCADO uses the foreground window's center to cover only
the display containing that window. Window metadata is checked in memory and is
not stored or sent to the AI service. An empty list disables window inspection.

On macOS, foreground-window details require Accessibility permission for the
terminal or packaged application. On X11 Linux, install `xprop` and `xwininfo`
(provided by `x11-utils` on Ubuntu). WSL can only inspect window metadata that
WSLg exposes; use a native Windows build to match all Windows applications.

## Supported platforms

- Windows 10/11
- macOS
- Linux with native X11 or Wayland screen capture, including WSLg

Wayland uses the desktop's ScreenCast Portal and PipeWire. Approve the displays
in the system picker when protection starts. Explicitly cancelling or denying
that request stops capture instead of bypassing the decision through MSS.

Runtime platform integration is isolated under `app/platforms/`:

- `windows.py` contains User32/Kernel32 foreground-window access, DPI setup,
  Windows data paths, and native runtime guidance.
- `macos.py` contains System Events foreground-window access, macOS data paths,
  and permission guidance.
- `linux.py` contains X11 foreground-window access, XDG data paths, and the Qt
  WebView setup used by Linux and WSLg.

Each process creates one `PlatformAdapter` and passes it to capture, blocklist,
overlay, storage, and dashboard composition. Business modules therefore do not
select an operating system or import a concrete platform implementation.

## Setup

Use Python 3.12 and create a virtual environment.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/download_models.py
python main.py
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_models.py
python main.py
```

On first launch, allow Terminal or LAVOCADO under **System Settings → Privacy &
Security → Screen & System Audio Recording**, then restart the application.
Browser address-bar discovery also requires **Privacy & Security → Accessibility**;
without that permission, website context remains UNKNOWN.

### Ubuntu, Linux, or WSL

```bash
sudo apt install \
  python3-tk x11-utils libpulse0 libxkbcommon-x11-0 libxcb-shm0 \
  gstreamer1.0-tools gstreamer1.0-pipewire \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-util1 libxcb-xkb1 \
  gcc libcairo2-dev pkg-config python3-dev \
  libgirepository-2.0-dev gir1.2-atspi-2.0
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_models.py
python main.py
```

Linux explicitly selects pywebview's Qt backend. PyGObject/AT-SPI is used only
for foreground browser address-bar discovery; if desktop accessibility is
unavailable, the website remains UNKNOWN and visual protection continues.
Under WSLg, LAVOCADO defaults
Qt WebEngine to software rendering to avoid Mesa/Zink failures when no DRM
render node is exposed. User-provided Qt or Mesa environment values are not
overwritten.

Validate the current Linux capture route without opening a capture session:

```bash
python scripts/validate_linux_capture.py --self-check
```

Run the live validation on an actual X11, Wayland, or WSLg desktop with:

```bash
python scripts/validate_linux_capture.py
```

The live check requests two fresh frames from every selected display, validates
their dimensions, BGR format, and advancing sequence, then discards them. It
never saves or uploads pixels. On Wayland, approve every display in the system
picker. Cancelling the picker reports `permission_denied` without trying MSS.
The JSON result should report `linux_xshm` for X11,
`linux_pipewire_portal` for Wayland, or `mss` with a fallback reason when a
native backend is technically unavailable. See the complete
[Linux capture validation checklist](docs/linux-capture-validation.md) for the
GNOME, KDE, WSLg, permission, and multi-display matrix.

The pinned 640m model is about 99 MiB and is downloaded from NudeNet's official
GitHub release with byte-size and SHA-256 verification. It is excluded from Git.
If it is absent during a source run, LAVOCADO logs a warning and falls back to
NudeNet 320n; packaged builds require the verified 640m file.
Set `LAVOCADO_NUDENET_MODEL` to use a local 640m file at another path.

To compare 320n and 640m locally without saving any analysis output:

```bash
python scripts/benchmark_detectors.py /path/to/test-image-1.jpg /path/to/test-image-2.jpg
```

To compare the native capture path with MSS in isolated developer processes:

```bash
python -m pip install -r requirements-benchmark.txt
python scripts/benchmark_capture.py
```

The capture benchmark reports aggregate latency, frame age, CPU, resident
memory, display resolution, and capture-to-NudeNet-decision timing. It does not
retain or upload frames. See the
[capture benchmark guide](docs/capture-benchmark.md) for individual backend
commands, permission behaviour, and the resolution/monitor test matrix.

For release stability validation, run the capture soak tool for at least one
hour per platform and backend mode:

```bash
python scripts/soak_capture.py --backend auto --duration-seconds 3600
```

It detects stalled sequences, unhealthy backends, memory/resource growth,
fallback transitions, and incomplete cleanup without retaining frames. See the
[capture soak-testing guide](docs/capture-soak-testing.md) for the eight-hour
command, failure thresholds, and platform matrix.

### Optional context-model benchmark

The Viddexa five-class context model is currently an optional development
dependency and is not yet included in release packages. When installed, it is
used only to confirm a borderline NudeNet detection on an expanded local crop.
A Viddexa result by itself can never trigger protection, and `sexy` or `hentai`
does not promote a borderline result. Install and benchmark it with:

```bash
python -m pip install -r requirements-context.txt
python scripts/benchmark_context.py /path/to/test-image-1.jpg /path/to/test-image-2.jpg
```

The pinned model files are downloaded from Hugging Face, then inference runs
locally. Benchmark images are not uploaded or saved, and the command prints
only numbered results rather than input paths. If the dependencies or model are
unavailable, LAVOCADO remains able to run in NudeNet-only mode. The existing
2-of-3 temporal confirmation still applies after the fused candidate decision.

For small-content rescue, each monitor is divided into four tiles and only one
tile is context-classified per scan. A very high local `porn` score merely asks
the same NudeNet 640m instance to recheck that tile; Viddexa never creates a
candidate by itself. A rescued tile is pinned for the next two checks so the
existing 2-of-3 temporal verifier can confirm or reject the same region. Rescue
is disabled automatically when only the NudeNet 320n fallback is available.

Protection diagnostics are kept in a thread-safe in-memory snapshot. They
include model availability, latest scan latency, monitor number, top detector
metadata, context result, decision source, temporal history, and rescue
schedule. Capture health reports the preferred and active backend, fallback
state and reason, frame age, and detected display count. The snapshot uses an
explicit safe schema and never contains image pixels, screenshots, crops,
URLs, window titles, or image paths. It is not written to SQLite or sent to
OpenAI.

Every fresh frame also passes through a per-monitor change scheduler before
NudeNet inference. Native changed-region metadata is preferred when the active
backend provides it; otherwise LAVOCADO compares a bounded 64x64 grayscale map
in memory. The first frame, periodic safety frames, and temporal follow-up
frames after a candidate are always scanned. The change map is never written
to disk, added to diagnostics, or uploaded.

Source developers can explicitly test `Auto`, native-only, and MSS-only capture
paths. This override is environment-gated, is disabled in packaged user builds,
and is not exposed by the dashboard. See the
[developer capture override guide](docs/developer-capture-override.md) for the
cross-platform commands and permission-policy notes.

The implementation-to-requirement mapping and remaining physical-platform
checks are tracked in the
[native capture acceptance checklist](docs/native-capture-acceptance.md).

When protection is dashboard-owned, a fixed stdin/stdout message protocol
copies that safe snapshot from the protection child into dashboard memory.
Only start, stop, diagnostic-read, and test-intervention operations are
supported; the bridge cannot execute commands or access arbitrary files. A
manual test intervention is shown by the protection process on its GUI main
thread and does not create a SQLite protection event.

## Use LAVOCADO

Start protection directly (the existing default):

```bash
python main.py
```

Or open the WebView dashboard to start and stop protection, inspect live
diagnostics, test the intervention, and view recent privacy-safe events:

```bash
python main.py dashboard
```

The dashboard uses pywebview with local HTML, CSS, and JavaScript. It exposes
only the fixed `DashboardAPI`, waits for `pywebviewready` before reading state,
and uses private browsing mode. Linux installs use the Qt backend; Windows uses
WebView2 when available, and macOS uses the system WebKit view. Closing the
window stops and collects the dashboard-owned Protection child.

The dashboard launches protection as a separate process so the overlay remains
on the GUI main thread on Windows, macOS, and Linux. Closing the dashboard asks
the protection process to stop cleanly.

On a headless machine, inspect recent local events in the terminal:

```bash
python main.py events --limit 20
```

## Build desktop applications

Install the separate build dependency and build on the target operating system:

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
python scripts/download_models.py
python -m PyInstaller --noconfirm --clean lavocado.spec
```

The output is written under `dist/`. PyInstaller applications must be built on
each target operating system; a Windows executable or macOS application cannot
be produced directly from WSL/Linux.

The **Package** workflow can build downloadable Windows, macOS, and Linux
artifacts without requiring three local machines. Open the repository's
**Actions** tab, select **Package**, choose **Run workflow**, and download the
three artifacts when all matrix jobs finish. It also runs automatically for
tags beginning with `v`.

Packaged applications open the dashboard when launched without arguments. The
Windows and macOS artifacts are currently unsigned, so development machines may
show the normal unknown-publisher warning. Do not distribute them as a trusted
release until code signing is configured.

## Run tests

```bash
python -m unittest discover -s tests -v
```
