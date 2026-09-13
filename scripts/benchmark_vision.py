"""Vision-only benchmark: visual policy ground truth, no viewing intent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="Unused scenario metadata such as medical/art/education/news.",
    )
    parser.add_argument("images", nargs="*", type=Path)
    args = parser.parse_args()
    if args.label:
        print(
            "Scenario metadata is ignored by Vision Benchmark: "
            + ", ".join(args.label)
        )
    if not args.images:
        print("Vision Benchmark ground truth labels: violation, clear")
        print("This is Visual Policy Ground Truth, not viewing-purpose Allow.")
        return 0
    print(f"images={len(args.images)} (run a detector separately to score them)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
