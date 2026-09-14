# Context-first visual protection

LAVOCADO decides whether the current application or website needs visual
protection before it looks at pixels. Vision never infers medical, artistic,
educational, or news purpose. Those exceptions are user-managed whitelist
bypasses.

> LAVOCADO first uses application and website allow/deny rules to decide
> whether the current context needs visual protection. A blacklist is
> FORCE_BLOCK. A whitelist is FULL_BYPASS. Only NORMAL runs Vision. Vision
> asks whether the frame violates LAVOCADO's visual content rules. The user
> is responsible for content shown in a whitelisted context.

## Flow

```text
Foreground window
        ↓
Context discovery (app, and website if a supported browser)
        ↓
Context Policy
        ├── FORCE_BLOCK → Protection (no Vision)
        ├── FULL_BYPASS → skip Vision, keep light context discovery
        └── NORMAL → Vision Pipeline → Temporal → Protection
```

Website context UNKNOWN is NORMAL on the website side and is resolved with
the application rule. A blacklist always beats a whitelist.

## Layer ownership

| Layer | Owns | Must not |
| --- | --- | --- |
| ForegroundContextService | App / website identity | Capture backends, pixels |
| ContextPolicyService | FORCE_BLOCK / FULL_BYPASS / NORMAL | Screenshots, detector labels |
| VisionPipeline | NudeNet, optional YOLO, tile ranking | Hostnames, URLs, viewing purpose |
| DecisionEngine | VIOLATION / UNCERTAIN / CLEAR | Application or website identity |
| ProtectionRuntime / TemporalVerifier | Scan scheduling and confirmed visual violations on fresh frames | Viewing-purpose scores or UI decisions |
| LavocadoService / OverlayBackend | State, intervention, and target-display overlay | Interpreting NudeNet/YOLO class names |

Viddexa only ranks tiles. It cannot block. Detectors emit `ViolationEvidence`.
The decision engine classifies visual evidence. Protection runs only after
context policy or confirmed temporal visual violations.

## Visual violation

Vision maps model labels onto:

- `sexual_act`
- `genital_exposure`
- `anus_exposure`
- `breast_exposure`
- `buttocks_exposure`

Strong evidence is confirmed on an original-resolution ROI when possible, then
on 2 of 3 fresh frames. Full scan, ROI, and tile rechecks that share a frame
sequence count as one temporal observation.

## Benchmarks

Keep these scoreboards separate within the Developer Dashboard's Benchmark Lab:

| Lab | Question | Not the question |
| --- | --- | --- |
| Vision Pipeline | Does this image violate visual policy? | Is the site medical/art/education? |
| Context Policy | Does the typed foreground fixture resolve to NORMAL, BYPASS, or BLOCK? | Do pixels violate visual policy? |
| Viddexa ranking fixture (Tools & Hardware) | Did ranking put the right tile first? | Is Viddexa porn accuracy Block accuracy? |
| Detector | Recall, precision, small-target, ROI/tile, latency | Viewing purpose |
| Full Protection Pipeline | Context + Vision if NORMAL + Temporal + final action | A single raw detector hit |
| Capture performance/stability (Tools & Hardware) | How does the real backend perform on this display? | Static image classification |

Medical anatomy that matches visual policy is a Vision true positive. The
same image on a whitelisted site is FULL_BYPASS: Vision is not called, and
the product allows it.

## Privacy

Context keeps only the identifiers needed for rules. Vision pixels stay in
memory. Do not persist full URLs, paths, queries, window titles, DOM,
screenshots, or crops. Whitelist contexts must not run hidden vision or keep
screenshots.
