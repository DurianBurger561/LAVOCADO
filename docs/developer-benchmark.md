# Developer benchmark contracts

The Developer Benchmark Lab has four dataset targets. Capture is a separate
hardware benchmark because it needs a real display, capture permission, and
platform backend. All five are local-only; benchmark images are neither
uploaded nor saved in result files.

| Target | Production components exercised | Result |
| --- | --- | --- |
| Detector Only | `PrimaryDetector.detect` → `ViolationEvidence` | Raw evidence and inference latency; no product Block/Allow score |
| Vision Pipeline | `CaptureFrame` → `FramePreprocessor` → `VisionPipeline`/`DecisionEngine` | Single-frame visual decision; no context or temporal confirmation |
| Context Policy | `ForegroundContext` → `ContextPolicyService` | `normal`, `full_bypass`, or `force_block`; no image or detector load |
| Full Protection Pipeline | Context Policy → Vision Pipeline if `normal` → `ProtectionRuntime`/`TemporalVerifier` | Final Block/Allow after policy or fresh-frame confirmation |
| Capture | Platform capture backend → `CaptureFrame` | Hardware latency, frame age, backend health and resource usage |

The Lab replays a still image as distinct fresh `CaptureFrame` fixtures with
changed-region metadata for temporal tests. This exercises the production
pipeline but does **not** measure live capture, foreground discovery, overlay
rendering, or end-to-end wall-clock responsiveness. Use the capture benchmark
and manual Protection smoke tests for those boundaries. A Full Protection row
with `force_block` or `full_bypass` skips image loading and detector inference.

Each sample in `benchmark_data/<dataset>/dataset.json` may include a
`context_fixture` and an `expected_policy`. For example:

```json
{
  "id": "case-1",
  "path": "images/case-1.png",
  "expected": "allow",
  "excluded": false,
  "tags": ["medical"],
  "expected_policy": "full_bypass",
  "context_fixture": {
    "application_identifier": "org.example.browser",
    "is_browser": true,
    "website_state": "known",
    "website_hostname": "trusted.example",
    "website_rules": [
      {
        "domain": "trusted.example",
        "action": "full_bypass",
        "match_mode": "exact_host"
      }
    ]
  }
}
```

`application_rules` entries use `identifier` and `action`; `website_rules`
entries use `domain`, `action`, and optional `match_mode`
(`exact_host` or `domain_and_subdomains`). Both accept `enabled`. The fixture
only stores app identifiers and hostnames, never full URLs, titles, or pixels.
Without a fixture, policy is `normal`. Context Policy accuracy requires
`expected_policy`; Block/Allow accuracy for Vision and Full Protection uses
`expected`. An unlabelled row does not contribute to accuracy.

Run the Capture Benchmark separately on Windows or macOS:

```bash
python -m pip install -r requirements-benchmark.txt
python scripts/benchmark_capture.py
```
