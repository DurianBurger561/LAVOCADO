# Bundled model license and size audit

Reviewed 2026-10-29 against the pinned model files in `app/vision/model_manifest.py`.
This is a release engineering assessment, not legal advice. The license of a
model repository, its base model, its weights, and its runtime must all be
checked before a BSL distribution is described as cleared for commercial use.

| Bundled component | Declared terms / issue | Current compressed Windows ZIP contribution |
| --- | --- | ---: |
| NudeNet `640m.onnx` | The upstream `v3.4-weights` tag contains AGPL-3.0 `LICENSE`. The `nudenet` 3.4.2 wheel contains an AGPL-3.0 license file even though its PyPI metadata says MIT. Treat the weights and runtime as unresolved for BSL redistribution. | 86.6 MiB |
| EraX YOLO11 NSFW Small | The fine-tuned model card declares Apache-2.0, but Ultralytics says YOLO11 models and its runtime are AGPL-3.0 or commercial Enterprise licensed. The package bundles `ultralytics` and the `.pt` weights. | 16.8 MiB for weights; PyTorch runtime adds much more |
| Viddexa Nano / Mini | Model cards declare Apache-2.0, a permissive license that generally permits commercial use with required notices. These are not MIT models. Check their base weights and include license notices before release. | 14.4 / 62.6 MiB |

The Windows v1.0.3 ZIP measured 517.8 MiB compressed and 1105.5 MiB extracted.
PyTorch's `torch_cpu.dll` alone used 82.5 MiB compressed; an optional Polars
native runtime used 51.7 MiB. This branch excludes Polars from PyInstaller
analysis and caps common native CPU pools plus NudeNet's ONNX session to two
threads by default. OpenCV frame transforms use one thread. The
`LAVOCADO_CPU_THREADS` environment variable can change the cap to 1–8.
Neither measure changes the model license status. The Windows bundle and CPU
behavior still need measurement on a Windows runner before claiming savings.

## MIT replacement candidate and functional gap

[OwenElliott/image-safety-classifier-xs](https://huggingface.co/OwenElliott/image-safety-classifier-xs)
declares MIT and provides a 13,137,569-byte ONNX file. It uses ONNX Runtime,
which is already needed by LAVOCADO, and predicts NSFW / NSFL / SFW.
Its author reports 97.76% accuracy on their own test set, which is not a
comparison with LAVOCADO's screen content. The `s` variant is 23,701,765
bytes and reports 97.99% on the same test set.

This model is an **image classifier**, not a body-part detector. It cannot
replace NudeNet's precise boxes or five anatomy classes. Converting its
whole-image NSFW score into a full-screen box would change local masking into
full-screen blocking and weaken the app's existing false-positive controls.
Before replacing the main detector, obtain a permissively licensed region
detector with clear base-weight provenance, or explicitly redesign and validate
the product around classifier-guided tile masking. Compare false positives,
misses, latency, and localized coverage on a representative, legally sourced
screen test set. Do not publish a purported MIT-only build while AGPL-linked
weights or runtime remain inside it.

## Sources

- [NudeNet `v3.4-weights` license](https://raw.githubusercontent.com/notAI-tech/NudeNet/v3.4-weights/LICENSE)
- [NudeNet PyPI 3.4.2 files and metadata](https://pypi.org/project/nudenet/3.4.2/)
- [Ultralytics YOLO11 licensing](https://docs.ultralytics.com/models/yolo11/)
- [EraX model card](https://huggingface.co/erax-ai/EraX-NSFW-V1.0)
- [Viddexa Nano](https://huggingface.co/viddexa/nsfw-detection-2-nano) and [Mini](https://huggingface.co/viddexa/nsfw-detection-2-mini) model cards
- [Owen Elliott XS model card](https://huggingface.co/OwenElliott/image-safety-classifier-xs)
