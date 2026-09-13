"""Record high-recall matrix metrics. Never prints a Recommended default."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.vision.benchmark_matrix import experimental_disclaimer, job_count, matrix
from app.vision.high_recall_benchmark import benchmark_report, matrix_jobs


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        return [item for item in payload["cases"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError("cases file must be a JSON list or {\"cases\": [...]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        help="JSON labeled cases. Do not include screenshots or URLs.",
    )
    parser.add_argument(
        "--print-matrix",
        action="store_true",
        help="print measurement cells; none are recommended",
    )
    args = parser.parse_args()

    if args.print_matrix:
        payload = matrix()
        payload["job_count"] = job_count()
        payload["jobs_preview"] = matrix_jobs()[:3]
        print(json.dumps(payload, indent=2))
        print(experimental_disclaimer())
        return 0

    if args.cases is None:
        parser.error("pass --cases or --print-matrix")
    report = benchmark_report(load_cases(args.cases.expanduser().resolve()))
    print(json.dumps(report, indent=2))
    print(experimental_disclaimer())
    if report.get("recommended") is not None:
        raise SystemExit("Recommended must stay null until a full dataset is measured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
