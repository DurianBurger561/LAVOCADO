<p align="center">
  <img src="assets/logo.png" height="260" width="260" alt="LAVOCADO logo">
</p>

<h1 align="center">LAVOCADO / 小油果</h1>

<p align="center">
  <strong>Local-first AI protection for the whole desktop.</strong>
</p>

<p align="center">
  <a href="README.md"><b>English</b></a> |
  <a href="README.zh.md"><b>中文</b></a>
</p>

---

LAVOCADO is a local-first desktop protection application for **Windows 10/11 and macOS**.

Instead of relying only on website URLs or application names, LAVOCADO can analyze what is actually displayed on screen. Visual evidence is processed locally, rechecked when necessary, confirmed across fresh frames, and followed by a deliberate intervention on the affected monitor.

LAVOCADO is built for **self-directed abstinence** — for people who have decided, on their own terms, to stay away from pornographic and sexually explicit content. It is a tool for keeping a boundary you set for yourself, not a parental-control or surveillance product. Rather than only blocking, it turns each trigger into a deliberate pause, so you can interrupt the impulse and choose what to do next.

## Why LAVOCADO?

Unwanted visual content can appear almost anywhere:

- browsers
- social and chat applications
- video players
- image viewers
- local files
- multiple monitors

Traditional URL blockers cannot reliably cover all of these cases.

LAVOCADO combines **user-controlled context rules** with **local visual AI** to enforce boundaries across the desktop.

---

## How It Works

LAVOCADO separates **user intent** from **visual judgment**.

```text
Foreground Application / Website
              ↓
        Context Policy
              ↓
 ┌────────────┼────────────┐
 ↓            ↓            ↓
FORCE_BLOCK FULL_BYPASS   NORMAL
 ↓            ↓            ↓
Protect     Skip Vision   Visual AI
                           ↓
                     Confirmation
                           ↓
                      Intervention
```

Rule priority:

```text
FORCE_BLOCK > FULL_BYPASS > NORMAL
```

- **FORCE_BLOCK** — a blocked app or website immediately triggers protection.
- **FULL_BYPASS** — a trusted app or website temporarily skips visual protection.
- **NORMAL** — LAVOCADO analyzes the screen normally.

A blacklist always takes priority over a whitelist.

Trusted contexts can be used for medical, educational, artistic, news, or other user-approved content.

---

## Visual Protection Pipeline

For normal contexts:

```text
Screen Capture
     ↓
Change Scheduling
     ↓
Scan Planning
     ↓
NudeNet + YOLO11
     ↓
Visual Evidence
     ↓
ROI / Tile Verification
     ↓
Candidate Tracking
     ↓
Fresh-frame Confirmation
     ↓
Protection
```

LAVOCADO does not immediately intervene after one weak model result.

Suspicious regions can be:

- rechecked from the original full-resolution frame
- analyzed as a higher-resolution region of interest
- recovered through tile-based scanning
- tracked across frames
- confirmed across independent fresh frames

This improves recall without simply lowering thresholds and increasing false positives.

---

## AI Models

LAVOCADO uses pinned and locally verified visual models:

- **NudeNet 640m** — primary explicit-content detection
- **YOLO11 NSFW Small** — additional visual evidence
- **Viddexa Nano / Mini** — visual region ranking

Viddexa helps decide **where the primary detectors should look next**. It does not directly trigger protection.

---

## Intervention

When protection is confirmed, LAVOCADO shows an intervention on the affected monitor:

```text
Pause
  ↓
Breathe
  ↓
Ready
```

The goal is not only to classify content, but to create a deliberate interruption before the user continues.

---

## Optional AI Typing Meditation

The Ready stage can optionally include an AI-assisted typing meditation.

The companion can:

- respond to what the user says in the current session
- help the user reflect on what they want to do next
- guide a short typing practice
- support English or Chinese conversations

The AI companion is optional and independent from the core protection pipeline.

LAVOCADO does **not** send screenshots, detection labels, confidence scores, application names, URLs, window titles, or browsing history to the LLM automatically.

Remote AI requests may contain:

- the current conversation
- recent typing-practice text
- today's aggregate trigger count
- a coarse time-of-day bucket

If AI meditation is disabled, unavailable, or fails, LAVOCADO falls back to local guidance.

The AI companion is designed as supportive guidance, not therapy or medical advice.

### Recommended configuration

The current default/recommended model is:

```text
gpt-4o-mini
```

Configure it from:

```text
Dashboard → Settings → AI typing meditation
```

You will need:

- an API key
- a compatible Chat Completions endpoint
- a model compatible with the current request format

OpenAI API usage is billed separately from a ChatGPT subscription.

For provider compatibility, API parameters, environment-variable configuration, troubleshooting, and key-storage details, see the dedicated AI meditation documentation.

---

## Privacy

LAVOCADO is designed to keep sensitive visual data local.

### Screen data

LAVOCADO does not store:

- screenshots
- image crops
- pixel data

Visual data is processed locally and kept only as necessary in memory.

### Browser context

Website rules persist only the normalized hostname required for the rule.

LAVOCADO does not persist:

- full URLs
- URL paths
- query parameters
- window titles

### Protection history

Protection history contains only limited metadata such as:

- event time
- trigger type
- confidence
- monitor number
- whether an intervention was shown

A rule-triggered event does not become a browsing-history record.

### AI meditation

Conversation text is held in application memory and is separate from protection-event history.

Anything the user manually types or pastes into the AI conversation may be sent to the configured API provider.

Saved API credentials are currently stored locally in application settings. Do not commit or share that settings file.

---

## Features

- Local visual content detection
- Multi-frame confirmation
- Multi-monitor isolation
- Application blacklist and whitelist
- Website blacklist and whitelist
- Context-first protection policy
- High-resolution ROI verification
- Tile-based small-target recovery
- Candidate tracking
- Local dashboard
- Detection presets
- Model management
- Privacy-safe diagnostics
- Local protection history
- Optional AI typing meditation
- English and Chinese interface
- Offline model verification
- Packaged-build self-check

---

## Supported Platforms

### Windows 10 / 11

- native desktop capture
- foreground application detection
- browser context through Windows UI Automation

### macOS

- ScreenCaptureKit
- foreground application detection
- browser context through Accessibility APIs

On macOS, allow LAVOCADO or your terminal under:

- **System Settings → Privacy & Security → Screen & System Audio Recording**
- **System Settings → Privacy & Security → Accessibility**

Screen Recording is required for protection. Accessibility is required for application and browser context detection.

---

## Quick Start

### Requirements

- Python 3.12
- Windows 10/11 or macOS

Clone the repository:

```bash
git clone https://github.com/DurianBurger561/LAVOCADO.git
cd LAVOCADO
```

### Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python scripts/download_models.py --model all
python main.py --self-check
python main.py dashboard
```

### macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python scripts/download_models.py --model all
python main.py --self-check
python main.py dashboard
```

---

## Usage

Run protection directly:

```bash
python main.py
```

or:

```bash
python main.py protect
```

Open the dashboard:

```bash
python main.py dashboard
```

View recent privacy-safe events:

```bash
python main.py events --limit 20
```

Run the local health check:

```bash
python main.py --self-check
```

The dashboard can be used to:

- start and stop protection
- configure application and website rules
- change visual settings
- apply detection presets
- manage local models
- view diagnostics
- test the intervention
- view recent events
- configure AI typing meditation

---

## Architecture

```text
                    Local Dashboard
                          │
                          ▼
               Protection Controller
                          │
                    child process
                          ▼
                    LavocadoService
                   /               \
             Context               Vision
               │                    │
               ▼                    ▼
        Context Policy         CaptureFrame
               │                    │
      ┌────────┼────────┐           ▼
      ↓        ↓        ↓    ProtectionRuntime
   BLOCK    BYPASS    NORMAL         │
      │        │        │            ▼
      │        │        └──────→ Visual Pipeline
      │        │                     │
      │        │                     ▼
      │        │              Temporal Verify
      │        │                     │
      └────────┴─────────────────────┘
                          │
                          ▼
                     Intervention
```

Important boundaries:

- Context decides **whether Vision runs**.
- Vision decides **what visual evidence exists**.
- Detectors produce evidence; they never trigger protection directly.
- Viddexa ranks regions; it does not decide protection.
- Temporal confirmation uses independent fresh frames.
- Visual runtime state is isolated per monitor.
- Platform-specific APIs stay behind platform adapters.

---

## Reliability

LAVOCADO treats models and packaged assets as part of the product.

```text
Pinned Model Manifest
        ↓
Download
        ↓
Integrity Verification
        ↓
Offline Runtime Verification
        ↓
PyInstaller
        ↓
Frozen Self-Check
```

Required models are verified before release packaging.

Run:

```bash
python main.py --self-check
```

to validate the local or packaged application.

---

## Build

Install build dependencies:

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
```

Download the required models:

```bash
python scripts/download_models.py --model all
```

Build:

```bash
python -m PyInstaller --noconfirm --clean lavocado.spec
```

The generated application is written to:

```text
dist/
```

Windows and macOS applications must be built on their respective target operating systems.

---

## Tests

Run the full test suite:

```bash
python -m unittest discover -s tests -v
```

---

## Project Structure

```text
LAVOCADO/
├── main.py
├── app/
│   ├── context/          # foreground app/site discovery and policy
│   ├── intervention/     # intervention sequence and event history
│   ├── platforms/        # Windows/macOS integrations
│   ├── settings/         # typed runtime settings
│   ├── ui/               # dashboard and overlay
│   └── vision/           # visual AI pipeline
│
├── scripts/              # model download and verification tools
├── tests/
├── lavocado_packaging/   # shared packaging helpers
└── lavocado.spec
```

---

## What Makes LAVOCADO Different?

| Capability                       | URL-only blocker | Single-image NSFW classifier | LAVOCADO |
| -------------------------------- | ---------------: | ---------------------------: | -------: |
| Website rules                    |              Yes |                           No |      Yes |
| Application rules                |          Limited |                           No |      Yes |
| Protects final desktop pixels    |               No |                          Yes |      Yes |
| Local visual processing          |              N/A |                      Depends |      Yes |
| High-resolution recheck          |               No |                   Usually no |      Yes |
| Fresh-frame confirmation         |               No |                   Usually no |      Yes |
| Multi-monitor isolation          |               No |                         Rare |      Yes |
| User-controlled trusted contexts |          Limited |                           No |      Yes |
| Deliberate intervention flow     |          Limited |                           No |      Yes |

---

## Design Principle

> **User intent belongs to policy.
> Visual judgment belongs to AI.
> Sensitive screen data stays local.**

LAVOCADO turns a user's chosen digital boundary into a practical, privacy-conscious desktop protection system.
