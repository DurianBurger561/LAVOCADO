"""Assert a Developer artifact includes Benchmark Lab and the user dashboard."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REQUIRED_MARKERS = (
    "developer/benchmark",
    "lab.js",
)


def verify_developer_bundle(root: Path) -> list[str]:
    errors: list[str] = []
    if not root.exists():
        return [f"Developer bundle is missing: {root}"]
    names = {path.name for path in root.rglob("*") if path.is_file()}
    if "lab.js" not in names:
        errors.append("Benchmark Lab UI (lab.js) is missing")
    if "index.html" not in names:
        errors.append("User dashboard HTML is missing")
    if "app.js" not in names:
        errors.append("User dashboard JS is missing")
    text_blob = " ".join(path.as_posix() for path in root.rglob("*"))
    if "developer" not in text_blob.lower() and "lab.js" not in names:
        errors.append("developer/benchmark modules are missing")
    py_files = [path for path in root.rglob("*.py") if "benchmark" in path.as_posix().lower()]
    pyc_files = [path for path in root.rglob("*.pyc") if "benchmark" in path.as_posix().lower()]
    if not py_files and not pyc_files and "lab.js" not in names:
        errors.append("Benchmark Lab python modules are missing")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Developer bundle includes Benchmark Lab")
    parser.add_argument("root", nargs="?", default="dist/LAVOCADO-Developer")
    args = parser.parse_args(argv)
    root = Path(args.root)
    errors = verify_developer_bundle(root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Developer bundle OK: Benchmark Lab present in {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
