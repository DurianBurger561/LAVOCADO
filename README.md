<p align="center">
  <img src="assets/logo.png" height="300" width="300" alt="LAVOCADO logo">
</p>

<h1 align="center">LAVOCADO / 小油果</h1>

<p align="center">
  <a href="README.md"><b>English</b></a> |
  <a href="README.zh.md"><b>中文</b></a>
</p>

LAVOCADO is a local-first desktop protection tool for Windows and macOS.

It detects visually explicit content on screen, confirms detections across multiple frames, and displays a local intervention on the affected monitor.

Screenshots are processed locally and are **not stored or transmitted**.

## Features

- Local visual content detection
- Multi-frame confirmation to reduce false positives
- Multi-monitor support
- Application and website blocklists
- Trusted application and website whitelists
- Local dashboard for settings, rules, diagnostics, and history
- Windows 10/11 and macOS support

## Privacy

LAVOCADO is designed to keep screen content local.

It does not store:

- Screenshots or image crops
- Full URLs
- Window titles

Protection history contains only limited metadata such as the event time, trigger type, confidence, monitor number, and whether an intervention was shown.

Website rules store only the hostname, not URL paths or query parameters.

## Protection Rules

Rules can be configured from the dashboard for:

- Blocked applications
- Whitelisted applications
- Blocked websites
- Whitelisted websites

Rule priority is:

```text
FORCE_BLOCK > FULL_BYPASS > NORMAL
```

- **Blocked context:** protection is triggered immediately.
- **Whitelisted context:** visual protection is temporarily skipped.
- **No matching rule:** normal visual detection runs.

A blacklist always takes priority over a whitelist.

Whitelists are intended for trusted contexts such as medical, educational, artistic, or news content that may legitimately contain explicit anatomy.

## Requirements

- Python 3.12
- Windows 10/11 or macOS

## Setup

Clone the repository and create a virtual environment.

### Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/download_models.py --model all
python main.py
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_models.py --model all
python main.py
```

On macOS, allow LAVOCADO or your terminal under:

- **System Settings → Privacy & Security → Screen & System Audio Recording**
- **System Settings → Privacy & Security → Accessibility**

Screen Recording is required for protection. Accessibility is required for application and browser context detection.

## Usage

Start protection directly:

```bash
python main.py
```

Open the dashboard:

```bash
python main.py dashboard
```

The dashboard can be used to:

- Start and stop protection
- Configure application and website rules
- Change vision settings
- Manage local models
- View diagnostics
- Test the intervention
- View recent protection events

### AI typing meditation

When the intervention reaches the Ready stage, an AI companion panel appears on the right. Without an API key, it uses a built-in local script and remains fully usable for the check-in and five typing-meditation rounds.

To use OpenAI or another OpenAI-compatible provider such as DeepSeek, set these variables before starting LAVOCADO:

```bash
export LAVOCADO_LLM_API_KEY="your API key"
export LAVOCADO_LLM_ENDPOINT="https://api.deepseek.com/v1"
export LAVOCADO_LLM_MODEL="deepseek-chat"
python main.py
```

For OpenAI, the endpoint and model variables can be omitted; the defaults are `https://api.openai.com/v1/chat/completions` and `gpt-4o-mini`. In Windows PowerShell, use `$env:LAVOCADO_LLM_API_KEY = "your API key"`. The key is used in memory for requests and is not written to the local database.

Only today's trigger count, a coarse time-of-day bucket, and text the user actively enters are sent to the model. Screenshots, detection labels, confidence values, URLs, window titles, and browsing history are never sent.

View recent events from the terminal:

```bash
python main.py events --limit 20
```

## Self Check

Verify the local installation and required assets:

```bash
python main.py --self-check
```

This checks the application environment, settings, local database, platform integration, and required models.

## Build

Install the build dependencies:

```bash
python -m pip install -r requirements.txt -r requirements-build.txt
python scripts/download_models.py --model all
```

Build with PyInstaller:

```bash
python -m PyInstaller --noconfirm --clean lavocado.spec
```

The generated application is written to `dist/`.

Windows and macOS applications must be built on their respective target operating systems.

## Tests

Run the test suite with:

```bash
python -m unittest discover -s tests -v
```
