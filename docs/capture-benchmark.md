# Capture backend benchmark

The Developer Benchmark Lab compares the platform-native capture backend with
MSS in isolated child processes. It never saves screenshots, reports pixel
data, or uploads captured frames.

## Install and run

Install Developer dependencies and open Benchmark Lab → Tools & Hardware:

```bash
python -m pip install -r requirements.txt -r requirements-developer.txt
python developer_main.py dashboard
```

Select Capture performance → Native then MSS → Run Capture Benchmark. This runs
`native` first and `mss` second, with 3 warmup frames and 30 measured
fresh frames per display. Each backend gets a new process so model and native
resource allocation from one run cannot contaminate the other run.

Choose Auto, Native, or MSS for an individual run; adjust frame and warmup
counts in the same panel. Export scalar JSON or CSV from the tool result.

On macOS, approve the native system screen-capture request. If the
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
count unchanged between runs. The separate Capture stability panel covers
one-hour and eight-hour runs; this tool is for bounded performance sampling.
