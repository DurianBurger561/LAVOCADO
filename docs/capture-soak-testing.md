# Capture long-run stability testing

The Developer Benchmark Lab's Capture stability tool exercises one capture mode while retaining only the
latest in-memory frame. It emits privacy-safe progress metadata and a final JSON
summary; it never saves, serializes, or uploads screen pixels.

## Open the Developer Benchmark Lab

```bash
python -m pip install -r requirements.txt -r requirements-developer.txt
python developer_main.py dashboard
```

## Required one-hour runs

In Tools & Hardware → Capture stability, select Auto and 3600 seconds for the
production-policy hour. Repeat with Native and MSS independently. For the
recommended eight-hour run, select Auto and 28800 seconds. Stop Protection
before starting the test.

Progress metadata is updated every 60 seconds. It contains elapsed time, frame
count, active backend, fallback state, RSS, thread count, and the platform's
native handle or file-descriptor count. Lab history and JSON/CSV exports store
only this scalar metadata, never screenshots.

## What constitutes a failure

The Lab marks the run failed when:

- a monitor stops producing an advancing sequence for 5 seconds;
- a frame changes shape, dtype, channel format, or monitor identity;
- the backend reports an unhealthy state;
- stopping does not release the active backend and monitor collection;
- post-start or post-stop RSS growth exceeds 256 MiB;
- post-stop threads, handles, or file descriptors grow beyond the configured
tolerance of 32;
- capture permission is denied (exit code 2, with no automatic MSS bypass).

The Lab currently uses fixed conservative growth thresholds. Record the
reason if a future experiment changes them.

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

During at least one run, test lock/unlock, display sleep/resume, fullscreen
content, and connecting or disconnecting an external display. Record whether a
backend transition occurred and whether fallback stayed active until restart.
Permission-denial tests must use `Auto` or `Native`; forced MSS is an explicit
developer path and is not a valid permission-policy test.

GitHub Actions runs the deterministic unit tests only. It cannot replace these
hour-long tests because hosted runners do not provide representative physical
displays, desktop permission prompts, sleep/resume, or hot-plug behaviour.
