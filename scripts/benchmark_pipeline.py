"""Full Pipeline Benchmark: Context Policy + Vision + Protection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.context.models import ContextPolicyAction
from app.vision.benchmarking import evaluate_full_pipeline, format_failure_explorer
from app.vision.violation_policy import VisualViolationClassification


def parse_action(value: str) -> ContextPolicyAction:
    try:
        return ContextPolicyAction(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"unknown action {value!r}; use force_block, full_bypass, or normal"
        ) from error


def parse_classification(value: str) -> str:
    try:
        return VisualViolationClassification(value).value
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"unknown classification {value!r}; use violation, uncertain, or clear"
        ) from error


def parse_detections(value: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError("detections must be JSON") from error
    if not isinstance(payload, list):
        raise argparse.ArgumentTypeError("detections must be a JSON list")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-action", type=parse_action, default=ContextPolicyAction.NORMAL)
    parser.add_argument("--website-action", type=parse_action, default=None)
    parser.add_argument(
        "--website-unknown",
        action="store_true",
        help="Treat website context as UNKNOWN (website action ignored).",
    )
    parser.add_argument(
        "--vision-classification",
        type=parse_classification,
        default=None,
        help="Vision result used only when policy resolves to NORMAL.",
    )
    parser.add_argument(
        "--detections",
        type=parse_detections,
        default=None,
        help='JSON detections, e.g. [{"class":"FEMALE_GENITALIA_EXPOSED","score":0.81}]',
    )
    parser.add_argument(
        "--temporal-confirmed",
        action="store_true",
        help="Treat confirmed visual violation as 2/N fresh frames.",
    )
    parser.add_argument(
        "--tag",
        default=None,
        help="Scenario metadata: medical, education, art, or news.",
    )
    args = parser.parse_args()
    website_action = None if args.website_unknown else args.website_action
    vision_result = (
        None
        if args.vision_classification is None
        else {"classification": args.vision_classification}
    )
    summary = evaluate_full_pipeline(
        app_action=args.app_action,
        website_action=website_action,
        vision_result=vision_result,
        temporal_confirmed=args.temporal_confirmed,
        detections=args.detections,
        scenario_tag=args.tag,
    )
    print("lab=full_pipeline_benchmark")
    print(
        f"policy={summary['policy']} vision_called={summary['vision_called']} "
        f"classification={summary['classification']} "
        f"protection={summary['protection']}"
    )
    print(f"failure_explorer {format_failure_explorer(summary)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
