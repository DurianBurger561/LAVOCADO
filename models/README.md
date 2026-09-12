# Local model assets

`640m.onnx` is downloaded from the official NudeNet `v3.4-weights` GitHub
release and intentionally excluded from Git because it is about 99 MiB.

From the repository root, run:

```bash
python scripts/download_models.py
```

The downloader pins the release asset, expected byte size, and SHA-256 digest.
PyInstaller packaging requires this verified file and includes it in the native
application. Source runs degrade to NudeNet's bundled 320n model if the file is
missing or cannot be loaded.
