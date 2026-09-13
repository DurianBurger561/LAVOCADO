"""Full-pipeline benchmark: Context Policy plus Vision plus Protection."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.context.models import ContextPolicyAction
from app.vision.benchmarking import evaluate_full_pipeline


def parse_action(value: str) -> ContextPolicyAction:
    try:
        return ContextPolicyAction(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"unknown action {value!r}; use force_block, full_bypass, or normal"
        ) from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-action", type=parse_action, default=ContextPolicyAction.NORMAL)
    parser.add_argument(
        "--website-action",
        type=parse_action,
        default=None,
    )
    parser.add_argument(
        "--website-unknown",
        action="store_true",
        help="Treat website context as UNKNOWN (website action ignored).",
    )
    args = parser.parse_args()
    website_action = None if args.website_unknown else args.website_action
    summary = evaluate_full_pipeline(
        app_action=args.app_action,
        website_action=website_action,
    )
    print(
        f"policy={summary['policy']} vision_called={summary['vision_called']} "
        f"protection={summary['protection']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
