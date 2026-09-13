"""Tile state, priority, and starvation protection."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.vision.regions import Region

PRIORITY_ALPHA = 0.50
PRIORITY_BETA = 0.30
PRIORITY_GAMMA = 0.20


@dataclass(slots=True)
class TileState:
    index: int
    region: Region
    context_score: float = 0.0
    change_score: float = 0.0
    skipped_scans: int = 0
    last_primary_scan_id: int | None = None
    priority_score: float = 0.0
    context_scores: dict[str, float] = field(default_factory=dict)


def age_score(skipped_scans: int, max_skip: int) -> float:
    if max_skip <= 0:
        return 1.0
    return min(1.0, max(0.0, skipped_scans / float(max_skip)))


def compute_priority(
    tile: TileState,
    *,
    max_skip: int,
    alpha: float = PRIORITY_ALPHA,
    beta: float = PRIORITY_BETA,
    gamma: float = PRIORITY_GAMMA,
) -> float:
    """Starved tiles jump the queue. Context never permanently hides a tile."""

    if tile.skipped_scans >= max_skip:
        tile.priority_score = float("inf")
        return tile.priority_score
    tile.priority_score = (
        alpha * float(tile.context_score)
        + beta * float(tile.change_score)
        + gamma * age_score(tile.skipped_scans, max_skip)
    )
    return tile.priority_score


def rank_tiles(
    tiles: list[TileState],
    *,
    max_skip: int,
    alpha: float = PRIORITY_ALPHA,
    beta: float = PRIORITY_BETA,
    gamma: float = PRIORITY_GAMMA,
) -> list[TileState]:
    for tile in tiles:
        compute_priority(tile, max_skip=max_skip, alpha=alpha, beta=beta, gamma=gamma)
    return sorted(tiles, key=lambda item: (-item.priority_score, item.index))


def mark_checked(tiles: list[TileState], checked_indexes: set[int], scan_id: int) -> None:
    for tile in tiles:
        if tile.index in checked_indexes:
            tile.skipped_scans = 0
            tile.last_primary_scan_id = scan_id
        else:
            tile.skipped_scans += 1
