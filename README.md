<p align="center">
  <img src="assets/神秘牛油果.png" length="300" width="300" alt="LAVOCADO logo">
</p>


<h1 align="center">LAVOCADO / 小油果</h1>

LAVOCADO is a local-first desktop protection tool. It monitors each connected
display independently, confirms visual risk across multiple frames, and covers
only the display that triggered protection.

Screenshots are processed locally and are not stored or sent to an LLM.

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
