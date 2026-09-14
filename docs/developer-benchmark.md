# Developer benchmark contracts

The Developer Benchmark Lab has four dataset targets plus Tools & Hardware.
All modes are local-only; benchmark images are neither uploaded nor saved in
result files. Open it with `python developer_main.py dashboard` after installing
`requirements.txt` and `requirements-developer.txt`.

| Target | Production components exercised | Result |
| --- | --- | --- |
| Detector Only | `PrimaryDetector.detect` → `ViolationEvidence` | Raw evidence and inference latency; no product Block/Allow score |
| Vision Pipeline | `CaptureFrame` → `FramePreprocessor` → `VisionPipeline`/`DecisionEngine` | Single-frame visual decision; no context or temporal confirmation |
| Context Policy | `ForegroundContext` → `ContextPolicyService` | `normal`, `full_bypass`, or `force_block`; no image or detector load |
| Full Protection Pipeline | Context Policy → Vision Pipeline if `normal` → `ProtectionRuntime`/`TemporalVerifier` | Final Block/Allow after policy or fresh-frame confirmation |
| Capture | Platform capture backend → `CaptureFrame` | Hardware latency, frame age, backend health and resource usage |
| NudeNet comparison | Same dataset → 320n and 640m raw detector | Visual-violation classification and latency; never product Block/Allow |
| Viddexa signal | Same dataset → local Nano or Mini | Ranking signal and latency; never product Block |
| Synthetic preprocessor | Generated pixels → `FramePreprocessor` | Uncached/prepared latency and pixel equivalence |
| Capture stability | Platform capture backend over time | Stall, resource-growth, fallback and release checks |

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

`expected_visual` is an optional, separate annotation: `violation`, `clear`,
or unlabelled. NudeNet 320n/640m visual recall and precision use only this
label, never the product `expected` label. Existing datasets without this
field remain unlabelled for visual accuracy. Tool runs are saved under
`benchmark_data/lab_runs/` as scalar JSON and can be exported as JSON or CSV.

Use Tools & Hardware for Native/MSS comparisons, stability checks, ranking
fixtures, and manually labelled high-recall case reports. Stop Protection
before starting a tool. Native permission denial does not silently start MSS.
The high-recall matrix shows measurement targets, not completed runs or a
Recommended default. Physical Windows/macOS displays are required for capture
validation; CI runs deterministic mock tests only.

Install and open the Developer Dashboard:

```bash
python -m pip install -r requirements.txt -r requirements-developer.txt
python developer_main.py dashboard
```
