# Local model assets

All four vision models are required downloads from pinned sources. They are
excluded from Git because of size.

From the repository root, run:

```bash
python scripts/download_models.py
```

This fetches:

- NudeNet 640m (`640m.onnx`) from the official NudeNet `v3.4-weights` GitHub
  release, verified by byte size and SHA-256.
- YOLO11 NSFW Small (`yolo11.pt`) from Hugging Face
  `erax-ai/EraX-NSFW-V1.0` (`erax_nsfw_yolo11s.pt`), verified by byte size and
  SHA-256.
- Viddexa Nano and Viddexa Mini from Hugging Face with pinned revisions.

The dashboard Required models card can download the same catalog. Source runs
still fall back to NudeNet 320n if 640m is missing, and to NudeNet if YOLO
weights cannot load.
