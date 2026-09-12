# Capture backend benchmark

This source-development tool compares the platform-native capture backend with
MSS in isolated child processes. It never saves screenshots, reports pixel
data, or uploads captured frames.

## Install and run

Install the optional cross-platform RSS sampler:

```bash
python -m pip install -r requirements-benchmark.txt
```

Run the default comparison from the repository root:

```bash
python scripts/benchmark_capture.py
```

This runs `native` first and `mss` second, with 3 warmup frames and 30 measured
fresh frames per display. Each backend gets a new process so model and native
resource allocation from one run cannot contaminate the other run.

Run an individual mode or increase the sample size when needed:

```bash
python scripts/benchmark_capture.py --backend auto --frames 100
python scripts/benchmark_capture.py --backend native --frames 100
python scripts/benchmark_capture.py --backend mss --frames 100
```

On Wayland and macOS, approve the native system screen-capture request. If the
native run receives an explicit permission denial, a `both` comparison exits
with code 2 and skips MSS. It never treats denial as a technical fallback.

## Reported metrics

Results contain only aggregate scalar metadata:

- capture latency: time spent waiting for the next advancing frame;
- frame age: capture timestamp to frame retrieval, including median and p95;
- detection latency: production-sized BGR frame through NudeNet decision;
- capture-to-decision: capture timestamp through the completed NudeNet decision;
- process CPU percentage during measured frames;
- baseline, peak, and delta resident memory;
- monitor index, resolution, sample count, and candidate count;
- checks that timestamp metadata exists and frame sequences advance.

`capture_to_decision` begins at the backend frame timestamp. Measuring from a
physical on-screen content change requires controlled external stimulus and is
not inferred from screenshot pixels by this privacy-safe tool.

## Test matrix

Record results on each supported platform for the available combinations:

| Display setup | Native | MSS |
| --- | --- | --- |
| Single 1920x1080 | Required | Required |
| Single 2560x1440 | When available | When available |
| Single 3840x2160 | When available | When available |
| Dual monitor | Required | Required |

Keep the machine, display refresh rate, visible workload, model files, and frame
count unchanged between runs. Phase 16 covers one-hour and eight-hour stability
runs separately; this command is intended for bounded performance sampling.
