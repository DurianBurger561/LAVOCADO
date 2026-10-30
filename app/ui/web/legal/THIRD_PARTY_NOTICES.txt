# LAVOCADO v1.0.4 — license and third-party notices

Copyright (c) 2026 Sixuan Liu and Luran Wang.
LAVOCADO application code is licensed under AGPL-3.0-only (see LICENSE).
This release supersedes the BSL terms for this version, not historical releases.
There is no warranty. Personal and commercial use, modification and redistribution
are permitted subject to AGPL-3.0. The license does not grant trademark rights or
permission to imply endorsement by the LAVOCADO developers.

## Source and build instructions

The source matching this release, including build scripts, is available at:
https://github.com/DurianBurger561/LAVOCADO/tree/v1.0.4
Release source and dependency-source archives are provided alongside the binaries:
https://github.com/DurianBurger561/LAVOCADO/releases/tag/v1.0.4
See README.md and .github/workflows/package.yml for build/install instructions.
Downloaded model files are pinned by size and SHA-256 in app/vision/model_manifest.py.
Model weights are included in the binaries; the downloader retrieves the same files.

## Models

- NudeNet 3.4.2 / 320n and 640m: notAI-tech/NudeNet, AGPL-3.0.
  The wheel's LICENSE and upstream v3.4-weights LICENSE govern this release's
  compliance treatment despite the conflicting MIT field in PyPI metadata.
  https://github.com/notAI-tech/NudeNet/tree/v3.4-weights
  The application subclasses the loader to bound ONNX CPU threads and disable
  idle worker spinning; original model files are not modified.
- EraX-NSFW-V1.0: erax-ai, model card declares Apache-2.0;
  Ultralytics YOLO11 base/runtime obligations are covered by this AGPL distribution.
  https://huggingface.co/erax-ai/EraX-NSFW-V1.0
- Viddexa NSFW Detection 2 Nano / Mini: Kerem Bozgan, Abdullah Kirman,
  Fatih Cagatay Akyon; Apache-2.0 model cards. Fine-tuned from Google EfficientNet.
  https://huggingface.co/viddexa/nsfw-detection-2-nano
  https://huggingface.co/viddexa/nsfw-detection-2-mini
  Akyon and Temizel, "State-of-the-art in nudity classification: A comparative
  analysis", ICASSP Workshops, 2023.

## Runtime dependencies

Third-party components retain their original licenses. The packaged legal folder
contains the installed distributions' license/notice files, model cards, and an
inventory with exact versions. Key components include:

- Ultralytics, ultralytics-thop and ultralytics-platform: AGPL-3.0 family, https://github.com/ultralytics/ultralytics
- PyTorch / torchvision: BSD-style licenses, https://github.com/pytorch
- Transformers / Hugging Face Hub / tokenizers / safetensors: Apache-2.0
- ONNX Runtime: MIT, https://github.com/microsoft/onnxruntime
- NumPy: BSD-3-Clause; Pillow: HPND; OpenCV: Apache-2.0
- pywebview: BSD-3-Clause; MSS: MIT
- DXcam: MIT; comtypes: MIT; PyObjC: MIT
- PyInstaller: GPL-2.0-or-later with bootloader exception
- Inter font: SIL OFL-1.1, bundled in app/ui/web/fonts/Inter-OFL.txt

These notices do not relicense any third-party work or imply upstream endorsement.
