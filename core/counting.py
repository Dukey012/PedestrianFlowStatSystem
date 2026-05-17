import cv2
import numpy as np

from core.types import CountingSnapshot, TrackState


class RegionCounter:
    def __init__(self, missing_tolerance=2):
        self.region_norm = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.track_entered = {}
        self.total_crossing = 0
        self.active_durations = {}
        self.missing_tolerance = max(1, int(missing_tolerance))
        self.missing_counts = {}

    def set_region(self, region_norm):
        self.region_norm = region_norm

    def set_missing_tolerance(self, missing_tolerance):
        self.missing_tolerance = max(1, int(missing_tolerance))

    def get_region_pixels(self, frame_shape):
        height, width = frame_shape[:2]
        return [(int(x * width), int(y * height)) for x, y in self.region_norm]

    def process_tracks(self, tracks: list[TrackState], frame_shape, current_sec):
        region_pixels = self.get_region_pixels(frame_shape)
        current_ids_in_region = set()
        duration_records = []
        crossing_events = []
        visible_track_ids = set()

        for track in tracks:
            visible_track_ids.add(track.track_id)
            self.missing_counts.pop(track.track_id, None)
            x1, y1, x2, y2 = track.ltrb
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            inside = self.point_in_region(cx, cy, region_pixels)

            if inside:
                current_ids_in_region.add(track.track_id)
                if track.track_id not in self.track_entered:
                    self.track_entered[track.track_id] = True
                if track.track_id not in self.active_durations:
                    self.active_durations[track.track_id] = current_sec
            else:
                if track.track_id in self.track_entered:
                    del self.track_entered[track.track_id]
                    self.total_crossing += 1
                    crossing_events.append((track.track_id, current_sec))
                if track.track_id in self.active_durations:
                    enter_sec = self.active_durations.pop(track.track_id)
                    duration_records.append((track.track_id, enter_sec, current_sec))

        self._expire_missing_tracks(visible_track_ids, current_sec, duration_records)

        return CountingSnapshot(
            total_crossing=self.total_crossing,
            inside_count=len(current_ids_in_region),
            active_ids=current_ids_in_region,
            duration_records=duration_records,
            crossing_events=crossing_events,
        )

    def get_active_duration_records(self, current_sec):
        return [
            (track_id, enter_sec, current_sec)
            for track_id, enter_sec in self.active_durations.items()
        ]

    def _expire_missing_tracks(self, visible_track_ids, current_sec, duration_records):
        tracked_inside_ids = set(self.track_entered) | set(self.active_durations)
        missing_ids = tracked_inside_ids - visible_track_ids

        for track_id in missing_ids:
            missed_updates = self.missing_counts.get(track_id, 0) + 1
            if missed_updates < self.missing_tolerance:
                self.missing_counts[track_id] = missed_updates
                continue

            self.missing_counts.pop(track_id, None)
            self.track_entered.pop(track_id, None)
            if track_id in self.active_durations:
                enter_sec = self.active_durations.pop(track_id)
                duration_records.append((track_id, enter_sec, current_sec))

    @staticmethod
    def point_in_region(x, y, region_pixels):
        poly = np.array(region_pixels, dtype=np.float32)
        return cv2.pointPolygonTest(poly, (x, y), False) >= 0
