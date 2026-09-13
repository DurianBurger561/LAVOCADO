"""Assert a User artifact does not contain Benchmark Lab."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

FORBIDDEN_PATH_PARTS = (
    "developer/benchmark",
    "developer\\benchmark",
    "developer.benchmark",
)
FORBIDDEN_FILE_NAMES = {
    "lab.js",
    "lab.css",
    "lab.html",
}
FORBIDDEN_TEXT_MARKERS = (
    "Benchmark Lab",
    "developer.benchmark",
    "from developer",
    "import developer",
)


def iter_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


def verify_user_bundle(root: Path) -> list[str]:
    errors: list[str] = []
    if not root.exists():
        return [f"User bundle is missing: {root}"]
    for path in iter_files(root):
        relative = path.as_posix().lower()
        if any(part in relative for part in ("developer/benchmark", "developer.benchmark")):
            errors.append(f"Developer Benchmark Lab path present: {path}")
        if path.name in FORBIDDEN_FILE_NAMES:
            errors.append(f"Benchmark Lab asset present: {path}")
        if path.suffix in {".py", ".pyc", ".html", ".js"}:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "developer.benchmark" in text or "from developer" in text:
                if path.name not in {"verify_user_bundle.py", "verify_developer_bundle.py"}:
                    errors.append(f"Developer import leaked into user bundle: {path}")
    developer_dir = root / "developer"
    if developer_dir.is_dir() and any(developer_dir.rglob("*")):
        errors.append(f"developer/ package is present in the user bundle: {developer_dir}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify User bundle excludes Benchmark Lab")
    parser.add_argument("root", nargs="?", default="dist/LAVOCADO")
    args = parser.parse_args(argv)
    root = Path(args.root)
    errors = verify_user_bundle(root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"User bundle OK: Benchmark Lab absent in {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
