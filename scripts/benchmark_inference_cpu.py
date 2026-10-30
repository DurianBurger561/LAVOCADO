"""Synthetic scheduling benchmark, not an accuracy or desktop-use benchmark."""
from __future__ import annotations
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def measure(mode: str) -> dict:
    import numpy as np
    from nudenet import NudeDetector
    from app.vision.detectors.nudenet import BoundedNudeDetector
    cls = NudeDetector if mode == 'baseline' else BoundedNudeDetector
    model = cls(model_path=str(ROOT / 'models/640m.onnx'), inference_resolution=640, providers=['CPUExecutionProvider'])
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    model.detect(frame)
    wall, cpu = time.perf_counter(), time.process_time()
    latency = []
    for _ in range(8):
        started = time.perf_counter()
        model.detect(frame)
        latency.append((time.perf_counter() - started) * 1000)
        time.sleep(.75)
    return {'mode': mode, 'wall_seconds': time.perf_counter()-wall,
            'cpu_seconds': time.process_time()-cpu,
            'mean_inference_ms': sum(latency)/len(latency)}

if __name__ == '__main__':
    if len(sys.argv) > 1:
        print(json.dumps(measure(sys.argv[1])))
    else:
        rows = []
        for mode in ('baseline', 'bounded'):
            raw = subprocess.check_output([sys.executable, __file__, mode], text=True)
            rows.append(json.loads(raw.strip().splitlines()[-1]))
        report = {'platform': platform.platform(), 'scope': 'NudeNet 640m CPU-only, eight blank 720p inputs, 750 ms sleep; excludes capture/UI/other models and does not measure accuracy', 'measurements': rows}
        path = ROOT / f'LAVOCADO-{platform.system()}-CPU-benchmark.json'
        path.write_text(json.dumps(report, indent=2))
        print(path.read_text())
