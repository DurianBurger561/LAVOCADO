"""Candidate region tracking across fresh frames."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.vision.regions import (
    Region,
    center_distance,
    expand_region,
    region_center,
    region_iou,
    xywh_to_xyxy,
)
from app.vision.violation_policy import ViolationEvidenceType

IOU_MATCH = 0.30
CENTER_DISTANCE_FRACTION = 0.35
MAX_MISS = 3


@dataclass(slots=True)
class CandidateTrack:
    id: int
    monitor_index: int
    label: str | None
    box: Region
    evidence_type: ViolationEvidenceType | None = None
    previous_box: Region | None = None
    confidence_history: list[float] = field(default_factory=list)
    evidence_score: float = 0.0
    fresh_frame_hits: int = 0
    miss_count: int = 0
    source: str = "unknown"
    last_frame_sequence: int | None = None
    velocity: tuple[float, float] = (0.0, 0.0)

    @property
    def predicted_center(self) -> tuple[float, float]:
        cx, cy = region_center(self.box)
        vx, vy = self.velocity
        return (cx + vx, cy + vy)


class CandidateTracker:
    """Match detections to tracks with IoU, center distance, label, and monitor."""

    def __init__(
        self,
        *,
        iou_threshold: float = IOU_MATCH,
        max_miss: int = MAX_MISS,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.max_miss = max_miss
        self._next_id = 1
        self._tracks: dict[int, CandidateTrack] = {}

    def tracks(self, monitor_index: int | None = None) -> list[CandidateTrack]:
        items = list(self._tracks.values())
        if monitor_index is None:
            return items
        return [track for track in items if track.monitor_index == monitor_index]

    def active_track(self, monitor_index: int) -> CandidateTrack | None:
        candidates = [
            track
            for track in self.tracks(monitor_index)
            if track.miss_count == 0
        ]
        if not candidates:
            candidates = self.tracks(monitor_index)
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.evidence_score, item.fresh_frame_hits))

    def match_or_create(
        self,
        *,
        monitor_index: int,
        box: Region | None,
        label: str | None,
        confidence: float,
        source: str,
        frame_sequence: int | None,
        evidence_delta: float,
        evidence_type: ViolationEvidenceType | None = None,
    ) -> CandidateTrack | None:
        if box is None:
            return None
        match = self._best_match(monitor_index, box, label, evidence_type)
        if match is None:
            track = CandidateTrack(
                id=self._next_id,
                monitor_index=monitor_index,
                label=label,
                box=box,
                evidence_type=evidence_type,
                source=source,
            )
            self._next_id += 1
            self._tracks[track.id] = track
        else:
            track = match
            old_center = region_center(track.box)
            new_center = region_center(box)
            if (
                frame_sequence is not None
                and track.last_frame_sequence is not None
                and frame_sequence != track.last_frame_sequence
            ):
                track.velocity = (
                    new_center[0] - old_center[0],
                    new_center[1] - old_center[1],
                )
            track.previous_box = track.box
            track.box = box
            if label:
                track.label = label
            if evidence_type is not None:
                track.evidence_type = evidence_type
            track.source = source
        same_frame = (
            frame_sequence is not None
            and track.last_frame_sequence == frame_sequence
        )
        if not same_frame:
            track.fresh_frame_hits += 1
            track.last_frame_sequence = frame_sequence
            track.miss_count = 0
            track.confidence_history.append(float(confidence))
            track.evidence_score += float(evidence_delta)
        else:
            track.evidence_score = max(track.evidence_score, track.evidence_score + 0.0)
            if confidence:
                if track.confidence_history:
                    track.confidence_history[-1] = max(
                        track.confidence_history[-1], float(confidence)
                    )
                else:
                    track.confidence_history.append(float(confidence))
        return track

    def mark_miss(self, track: CandidateTrack, *, decay: float) -> None:
        track.miss_count += 1
        track.evidence_score *= float(decay)
        if track.miss_count >= self.max_miss or track.evidence_score < 0.05:
            self._tracks.pop(track.id, None)

    def mark_monitor_misses(
        self,
        monitor_index: int,
        *,
        hit_ids: set[int],
        decay: float,
        frame_sequence: int | None,
    ) -> None:
        for track in list(self.tracks(monitor_index)):
            if track.id in hit_ids:
                continue
            if (
                frame_sequence is not None
                and track.last_frame_sequence == frame_sequence
            ):
                continue
            self.mark_miss(track, decay=decay)

    def predicted_roi(
        self,
        track: CandidateTrack,
        image_shape: tuple[int, ...],
        expansion: float,
    ) -> Region | None:
        cx, cy = track.predicted_center
        left, top, right, bottom = track.box
        width = max(1, right - left)
        height = max(1, bottom - top)
        predicted = (
            round(cx - width / 2),
            round(cy - height / 2),
            round(cx + width / 2),
            round(cy + height / 2),
        )
        return expand_region(predicted, image_shape, expansion)

    def reset(self, monitor_index: int | None = None) -> None:
        if monitor_index is None:
            self._tracks.clear()
            return
        for track in self.tracks(monitor_index):
            self._tracks.pop(track.id, None)

    def _best_match(
        self,
        monitor_index: int,
        box: Region,
        label: str | None,
        evidence_type: ViolationEvidenceType | None,
    ) -> CandidateTrack | None:
        width = max(1, box[2] - box[0])
        height = max(1, box[3] - box[1])
        distance_threshold = max(width, height) * CENTER_DISTANCE_FRACTION
        best: tuple[float, CandidateTrack] | None = None
        for track in self.tracks(monitor_index):
            if (
                evidence_type is not None
                and track.evidence_type is not None
                and track.evidence_type is not evidence_type
            ):
                continue
            if not _labels_compatible(track.label, label):
                continue
            iou = region_iou(track.box, box)
            distance = center_distance(track.box, box)
            if iou >= self.iou_threshold or distance <= distance_threshold:
                score = max(iou, 1.0 - min(1.0, distance / max(distance_threshold, 1.0)))
                if best is None or score > best[0]:
                    best = (score, track)
        return None if best is None else best[1]


def box_to_region(box: object, *, xywh: bool = True) -> Region | None:
    """Convert a detector XYWH box or an XYXY region into a track box."""

    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        values = tuple(float(item) for item in box)
    except (TypeError, ValueError):
        return None
    if xywh:
        return xywh_to_xyxy(values)
    left, top, right, bottom = (int(item) for item in values)
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def _labels_compatible(existing: str | None, incoming: str | None) -> bool:
    if existing is None or incoming is None:
        return True
    return existing == incoming or existing.split("_")[0] == incoming.split("_")[0]
