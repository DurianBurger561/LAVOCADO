<p align="center">
  <img src="assets/神秘牛油果.png" length="300" width="300" alt="LAVOCADO logo">
</p>


<h1 align="center">LAVOCADO / 小油果</h1>

LAVOCADO is a local-first desktop protection tool. It monitors each connected
display independently, confirms visual risk across multiple frames, and covers
only the display that triggered protection.

Screenshots are processed locally and are not stored or sent to an LLM.

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

## Supported platforms

- Windows 10/11
- macOS
- Linux with X11-compatible screen capture, including WSLg

Wayland support depends on the compositor's screen-capture permissions.

## Setup

Use Python 3.12 and create a virtual environment.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

On first launch, allow Terminal or LAVOCADO under **System Settings → Privacy &
Security → Screen & System Audio Recording**, then restart the application.

### Ubuntu, Linux, or WSL

```bash
sudo apt install python3-tk
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

## Run tests

```bash
python -m unittest discover -s tests -v
```
