from deep_sort_realtime.deepsort_tracker import DeepSort

from core.exceptions import DetectionPipelineError
from core.types import DetectionBox, TrackState


class PersonTracker:
    def __init__(self, max_age=20, n_init=4):
        try:
            self.tracker = DeepSort(max_age=max_age, n_init=n_init)
        except Exception as exc:
            raise DetectionPipelineError(f"跟踪器初始化失败: {exc}") from exc

    def update(self, detections: list[DetectionBox], frame):
        tracker_input = [
            (detection.bbox_ltwh, detection.confidence, detection.class_id)
            for detection in detections
        ]
        try:
            tracks = self.tracker.update_tracks(tracker_input, frame=frame)
        except Exception as exc:
            raise DetectionPipelineError(f"目标跟踪失败: {exc}") from exc

        confirmed_tracks = []
        for track in tracks:
            if not track.is_confirmed():
                continue
            confirmed_tracks.append(
                TrackState(track_id=track.track_id, ltrb=tuple(track.to_ltrb()))
            )
        return confirmed_tracks
