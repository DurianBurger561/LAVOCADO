# Developer capture backend override

The capture override is available only in explicitly enabled source development
runs. Packaged PyInstaller applications always use `Auto`, and the dashboard
does not expose this setting to users.

Available modes:

| Mode | Behaviour |
| --- | --- |
| `auto` | Native backend first, with the existing policy-controlled MSS fallback |
| `native` | Native backend only; technical failures are not hidden by MSS |
| `mss` | MSS only, for debugging and capture A/B checks |

## macOS

Run one command from the repository root:

```bash
LAVOCADO_DEVELOPER_BUILD=1 LAVOCADO_CAPTURE_BACKEND=auto python main.py
LAVOCADO_DEVELOPER_BUILD=1 LAVOCADO_CAPTURE_BACKEND=native python main.py
LAVOCADO_DEVELOPER_BUILD=1 LAVOCADO_CAPTURE_BACKEND=mss python main.py
```

The same variables can be used with `python main.py dashboard`. The dashboard's
capture diagnostics show which backend became active.

## Windows PowerShell

Set the variables for the current terminal, then start from source:

```powershell
$env:LAVOCADO_DEVELOPER_BUILD = "1"
$env:LAVOCADO_CAPTURE_BACKEND = "native"
python main.py
```

Clear the variables when finished:

```powershell
Remove-Item Env:LAVOCADO_DEVELOPER_BUILD
Remove-Item Env:LAVOCADO_CAPTURE_BACKEND
```

`Auto` retains the permission policy: an explicit screen-capture permission
denial never activates MSS. Forced `Native` has no fallback. Forced `MSS` is an
intentional developer test path and must not be used to evaluate permission
denial behaviour.
