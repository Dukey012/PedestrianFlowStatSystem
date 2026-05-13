from deep_sort_realtime.deepsort_tracker import DeepSort

from core.types import DetectionBox, TrackState


class PersonTracker:
    def __init__(self, max_age=20, n_init=4):
        self.tracker = DeepSort(max_age=max_age, n_init=n_init)

    def update(self, detections: list[DetectionBox], frame):
        tracker_input = [
            (detection.bbox_ltwh, detection.confidence, detection.class_id)
            for detection in detections
        ]
        tracks = self.tracker.update_tracks(tracker_input, frame=frame)

        confirmed_tracks = []
        for track in tracks:
            if not track.is_confirmed():
                continue
            confirmed_tracks.append(
                TrackState(track_id=track.track_id, ltrb=tuple(track.to_ltrb()))
            )
        return confirmed_tracks
