from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionBox:
    bbox_ltwh: list[float]
    confidence: float
    class_id: int = 0


@dataclass(frozen=True)
class TrackState:
    track_id: int
    ltrb: tuple[float, float, float, float]


@dataclass(frozen=True)
class CountingSnapshot:
    total_crossing: int
    inside_count: int
    active_ids: set[int]
    duration_records: list[tuple[int, float, float]]


@dataclass(frozen=True)
class TrackSnapshot:
    frame_idx: int
    tracks: list[TrackState]
    total_crossing: int
    inside_count: int
