# Capture long-run stability testing

The soak tool exercises one capture mode continuously while retaining only the
latest in-memory frame. It emits privacy-safe progress metadata and a final JSON
summary; it never saves, serializes, or uploads screen pixels.

## Install the optional monitor

```bash
python -m pip install -r requirements-benchmark.txt
```

## Required one-hour runs

Run the normal production policy for at least one hour on each platform:

```bash
python scripts/soak_capture.py --backend auto --duration-seconds 3600
```

Then exercise the developer-only paths independently:

```bash
python scripts/soak_capture.py --backend native --duration-seconds 3600
python scripts/soak_capture.py --backend mss --duration-seconds 3600
```

The recommended eight-hour run is:

```bash
python scripts/soak_capture.py --backend auto --duration-seconds 28800
```

Progress lines are emitted every 60 seconds. They contain elapsed time, frame
count, active backend, fallback state, RSS, thread count, and the platform's
native handle or file-descriptor count. Redirecting stdout to a log file stores
only this scalar metadata, never screenshots.

## What constitutes a failure

The command returns a non-zero exit code when:

- a monitor stops producing an advancing sequence for 5 seconds;
- a frame changes shape, dtype, channel format, or monitor identity;
- the backend reports an unhealthy state;
- stopping does not release the active backend and monitor collection;
- post-start or post-stop RSS growth exceeds 256 MiB;
- post-stop threads, handles, or file descriptors grow beyond the configured
  tolerance of 32;
- capture permission is denied (exit code 2, with no automatic MSS bypass).

Adjust thresholds only when recording the reason:

```bash
python scripts/soak_capture.py \
  --max-memory-growth-mib 384 \
  --max-resource-growth 48
```

The final result includes median/p95/max capture latency and frame age, running
peak memory, running memory growth, estimated MiB/hour RSS trend, post-stop
growth, native resource counts, backend transitions, fallback reason, and
release status.

## Platform matrix

Complete the available rows before release:

| Platform/session | Auto 1h | Native 1h | MSS 1h | Auto 8h |
| --- | --- | --- | --- | --- |
| Windows DXGI | Required | Required | Required | Recommended |
| macOS ScreenCaptureKit | Required | Required | Required | Recommended |
| Linux GNOME Wayland | Required | Required | Required where available | Recommended |
| Linux KDE Wayland | Required | Required | Required where available | Recommended |
| Linux X11/Xorg | Required | Required | Required | Recommended |
| WSLg | Required | Required | Required | Recommended |

During at least one run, test lock/unlock, display sleep/resume, fullscreen
content, and connecting or disconnecting an external display. Record whether a
backend transition occurred and whether fallback stayed active until restart.
Permission-denial tests must use `Auto` or `Native`; forced MSS is an explicit
developer path and is not a valid permission-policy test.

GitHub Actions runs the deterministic unit tests only. It cannot replace these
hour-long tests because hosted runners do not provide representative physical
displays, desktop permission prompts, sleep/resume, or hot-plug behaviour.
