<p align="center">
  <img src="assets/logo.png" height="300" width="300" alt="LAVOCADO logo">
</p>

<h1 align="center">LAVOCADO / 小油果</h1>

<p align="center"><a href="README.md"><b>🇬🇧🇺🇸🇨🇦🇦🇺🇳🇿English<b></a> | <a href="README.zh.md"><b>🇨🇳中文<b></a></p>

LAVOCADO is a local-first desktop protection tool. It detects visually explicit
content in protected contexts, confirms it across multiple frames, and covers
only the display that triggered protection.

LAVOCADO does not determine viewing intent. Trusted applications or websites
can be whitelisted to bypass visual protection for medical, educational,
artistic, news, or other user-approved purposes.

Screenshots are processed locally and are not stored or sent to an LLM.
The primary whole-screen detector uses NudeNet 640m at 640-pixel inference.
The full-resolution capture remains only in memory for later local rechecks.

When a risk is confirmed, the affected display moves through a short pause,
one guided breath, and a ready stage before enabling the continue button.
`Esc` remains available as an emergency exit.

## Local data and privacy

When protection is triggered, LAVOCADO stores only the UTC time, trigger type,
confidence, monitor number, and whether the intervention was shown. Vision
events may also store the detector class. Application-rule and website-rule
events store a null label, so application identifiers and hostnames are not
written to history. It does not store screenshots, full URLs, or window titles.

The SQLite event database is stored in the current user's application-data
directory:

- Windows: `%LOCALAPPDATA%\\LAVOCADO\\events.db`
- macOS: `~/Library/Application Support/LAVOCADO/events.db`

Set `LAVOCADO_DATA_DIR` before starting the app to use a different directory.
The same file also stores `application_rules` and `website_rules`. Website
input is reduced to a hostname before saving; paths and query strings are never
saved as rules. Edit these rules in the dashboard while protection is stopped.
Protection loads them at startup.

See the [context privacy audit](docs/context_privacy_audit.md) for the
discovery, diagnostics, and history boundaries.

## Protection rules

The dashboard edits four local rule groups while protection is stopped.
Changes apply the next time protection starts:

- Blocked applications
- Whitelisted applications
- Blocked websites
- Whitelisted websites

Use **Pick current app** to fill a stable executable name or bundle ID from the
foreground window. Website fields accept a hostname or HTTPS URL; only the
hostname is saved. Matching can be exact-host or include
subdomains.

Adding a whitelist asks you to confirm that visual protection will be skipped
while that app or site is active, unless a higher-priority blacklist also
matches. Use the whitelist for trusted medical, educational, artistic, news,
or other non-pornographic sources that may still contain explicit anatomy.
You are responsible for content shown in a whitelisted context. LAVOCADO does
not treat a whitelist as a safety certification.

LAVOCADO first identifies the foreground application. If it is a supported
browser, it also reads the active-tab hostname through the platform
accessibility API (Windows UI Automation or macOS Accessibility).
It never guesses a site from the window title. If the address cannot be read,
website context stays UNKNOWN and only the application rule applies.

Application and website rules are evaluated independently, then combined:

```text
FORCE_BLOCK > FULL_BYPASS > NORMAL
```

A blacklist always wins over a whitelist. With no matching rules, protection
runs the existing vision pipeline unchanged.

Layer ownership is fixed: `ForegroundContextService` discovers context,
`ContextPolicyService` evaluates rules, `VisionPipeline` and `DecisionEngine`
judge visual evidence only, `ProtectionRuntime` schedules scans and confirms
fresh frames with `TemporalVerifier`, and `LavocadoService` owns state and
intervention. `OverlayBackend` receives the target `MonitorInfo` from capture.
Detectors never trigger
protection directly, and the decision engine never receives a hostname,
application name, or medical/art/education flag.

- `FORCE_BLOCK` immediately covers the display that contains the foreground
  window. NudeNet, YOLO, tile ranking, and temporal confirmation are skipped.
- `FULL_BYPASS` skips the entire vision pipeline while that context is active,
  then resumes from a fresh state when it leaves.
- `NORMAL` runs capture and visual-violation detection. Vision only asks
  whether the frame violates LAVOCADO's visual content rules; it does not
  classify medical, art, education, or news purpose. Confirmed violations
  still require 2-of-3 fresh frames before protection.

Live diagnostics show only coarse availability: whether an application was
identified, whether it is a browser, whether the website is known, and the
resulting rule actions. They do not include the application identifier,
hostname, window title, or URL.

The durable product rules are in
[context-first visual protection](docs/context-first-vision.md).

On macOS, foreground-application details require Accessibility permission for
the terminal or packaged application.

## Optional AI support message

LAVOCADO works without an API key and uses a built-in local message by default.
To enable a short AI-generated message in the final intervention stage, set an
OpenAI API key before starting the application:

```powershell
# Windows PowerShell
$env:OPENAI_API_KEY="your-api-key"
```

```bash
# macOS
export OPENAI_API_KEY="your-api-key"
```

Only a fixed request for a supportive message is sent. Screenshots, detector
labels, confidence values, monitor numbers, URLs, and window titles are never
included. API response storage is disabled for this request. Set
`LAVOCADO_OPENAI_MODEL` to override the default model.

## Supported platforms

- Windows 10/11
- macOS

Runtime platform integration is isolated under `app/platforms/`:

- `windows.py` contains User32/Kernel32 foreground-window access, DPI setup,
  Windows data paths, and native runtime guidance.
- `macos.py` contains System Events foreground-window access, macOS data paths,
  and permission guidance.

Website discovery is also platform-specific and lives under
`app/platforms/website/`: Windows UI Automation and macOS `AXUIElement`. A
failed or unavailable reader never stops visual protection; the website side
stays UNKNOWN.

Each process creates one `PlatformAdapter` for capture, context discovery,
storage, and dashboard composition. Overlay selection is isolated in the UI
backend factory; it does not rediscover monitors through MSS. Business modules
do not select an operating system or import a concrete platform implementation.

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

The pinned 640m model is about 99 MiB and is downloaded from NudeNet's official
GitHub release with byte-size and SHA-256 verification. It is excluded from Git.
If it is absent during a source run, LAVOCADO logs a warning and falls back to
NudeNet 320n; packaged builds require the verified 640m file.
Set `LAVOCADO_NUDENET_MODEL` to use a local 640m file at another path.

NudeNet 640m, YOLO11 NSFW Small, Viddexa Nano, and Viddexa Mini are all
required in both User and Developer packages. `requirements.txt` installs the
YOLO/Transformers/PyTorch inference dependencies. The dashboard Download all
button or `python scripts/download_models.py --model all` downloads the pinned
assets. Download and packaging both verify file sizes and SHA-256 digests;
packaging fails if any model is missing or invalid. The Viddexa snapshots are
copied into the artifact and loaded from the bundle offline, not from the
build runner's Hugging Face cache. This makes release artifacts substantially
larger. YOLO11 NSFW Small maps sexual-act and anatomy labels onto the same
visual-violation policy. A damaged local install still falls back to NudeNet.
To re-download only YOLO:

```bash
python scripts/download_models.py --model yolo11_nsfw_small
```

All benchmarks now live in the Developer Dashboard's Benchmark Lab:

```bash
python -m pip install -r requirements.txt -r requirements-developer.txt
python developer_main.py dashboard
```

The Lab contains the four dataset targets (Detector Only, Vision Pipeline,
Context Policy, Full Protection Pipeline), NudeNet 320n/640m comparison,
Viddexa signal and ranking diagnostics, high-recall case reports, a synthetic
preprocessor microbenchmark, and real-display Capture performance and stability
tests. Native and MSS Capture comparisons use isolated worker processes. Stop
Protection before starting a Lab tool. Medical, education, art, and news tags
never force Allow; visual-violation ground truth is annotated separately from
product Block/Allow. No benchmark saves or uploads captured screen pixels.
See the [Developer benchmark guide](docs/developer-benchmark.md),
[capture benchmark guide](docs/capture-benchmark.md), and
[capture stability guide](docs/capture-soak-testing.md).

Viddexa only prioritizes tiles for the primary detector; its signal is never
product Block accuracy. A missing optional runtime model does not prevent
NudeNet-only Protection. Confirmed visual violations still require 2-of-3
fresh frames before protection.

For small-content rescue, each monitor is divided into four tiles. Viddexa
ranks those tiles by porn/hentai risk; a high rank only asks the same NudeNet
640m instance to recheck that tile. A rescued tile is pinned for the next two
checks so the temporal verifier can confirm or reject the same region. Rescue
is disabled automatically when only the NudeNet 320n fallback is available.

Protection diagnostics are kept in a thread-safe in-memory snapshot. They
include model availability, latest scan latency, monitor number, top detector
metadata, context result, decision source, temporal history, rescue schedule,
and coarse foreground-policy state. Capture health reports the preferred and
active backend, fallback state and reason, frame age, and detected display
count. The snapshot uses an explicit safe schema and never contains image
pixels, screenshots, crops, URLs, window titles, application identifiers,
hostnames, or image paths. It is not written to SQLite or sent to OpenAI.

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
Only start, stop, diagnostic-read, test-intervention, and local rule-edit
operations are supported; the bridge cannot execute commands or access
arbitrary files. A manual test intervention is shown by the protection process
on its GUI main thread and does not create a SQLite protection event.

## Use LAVOCADO

Start protection directly (the existing default):

```bash
python main.py
```

Or open the WebView dashboard to start and stop protection, edit application
and website rules, inspect live diagnostics, test the intervention, and view
recent privacy-safe events:

```bash
python main.py dashboard
```

The dashboard uses pywebview with local HTML, CSS, and JavaScript. It exposes
only the fixed `DashboardAPI`, waits for `pywebviewready` before reading state,
and uses private browsing mode. Windows uses WebView2 when available, and
macOS uses the system WebKit view. Closing the window stops and collects the
dashboard-owned Protection child.

The dashboard launches protection as a separate process so the overlay remains
on the GUI main thread on Windows and macOS. Closing the dashboard asks
the protection process to stop cleanly.

On a headless machine, inspect recent local events in the terminal:

```bash
python main.py events --limit 20
```

## Build desktop applications

Install the separate build dependency and build on the target operating system:

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
python scripts/download_models.py --model all
python -m PyInstaller --noconfirm --clean lavocado.spec
```

The output is written under `dist/`. PyInstaller applications must be built on
each target operating system.

The **Package** workflow can build downloadable Windows and macOS artifacts
without requiring both local machines. Open the repository's **Actions** tab,
select **Package**, choose **Run workflow**, and download the four
User/Developer platform artifacts when all matrix jobs finish. It also runs
automatically for tags beginning with `v`.

Packaged applications open the dashboard when launched without arguments. The
Windows and macOS artifacts are currently unsigned, so development machines may
show the normal unknown-publisher warning. Do not distribute them as a trusted
release until code signing is configured.

## Run tests

```bash
python -m unittest discover -s tests -v
```
