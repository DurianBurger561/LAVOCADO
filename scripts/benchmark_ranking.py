"""Viddexa ranking lab: tile order and recall gain, never product Block."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.vision.ranking_benchmark import ranking_quality, recall_gain


def parse_tiles(value: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError("tiles must be JSON") from error
    if not isinstance(payload, list):
        raise argparse.ArgumentTypeError("tiles must be a JSON list")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tiles",
        type=parse_tiles,
        required=True,
        help=(
            'JSON tiles, e.g. [{"index":0,"scores":{"porn":0.99},"primary_hit":false},'
            '{"index":1,"scores":{"porn":0.2},"primary_hit":true}]'
        ),
    )
    parser.add_argument("--baseline-hits", type=int, default=0)
    parser.add_argument("--with-tile-hits", type=int, default=None)
    parser.add_argument("--positives", type=int, default=0)
    args = parser.parse_args()
    quality = ranking_quality(args.tiles)
    print("lab=viddexa_ranking_benchmark")
    print("Viddexa porn accuracy is not product Block accuracy.")
    print(
        f"metric_kind={quality['metric_kind']} "
        f"top_tile={quality['top_tile_index']} "
        f"reciprocal_rank={quality['reciprocal_rank']:.3f} "
        f"prioritized_primary_hit={quality['prioritized_primary_hit']} "
        f"product_block={quality['product_block']}"
    )
    if args.with_tile_hits is not None:
        gain = recall_gain(
            baseline_hits=args.baseline_hits,
            with_tile_hits=args.with_tile_hits,
            positives=args.positives,
        )
        print(
            f"metric_kind={gain['metric_kind']} "
            f"baseline_recall={gain['baseline_recall']:.3f} "
            f"tile_recall={gain['tile_recall']:.3f} "
            f"recall_gain={gain['recall_gain']:.3f} "
            f"product_block={gain['product_block']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
