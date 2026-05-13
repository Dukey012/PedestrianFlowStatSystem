import cv2
import numpy as np
from PySide6.QtCore import QMutex, QThread, QWaitCondition, Signal

from core.counting import RegionCounter
from core.detection import PersonDetector
from core.tracking import PersonTracker
from services.recorder import VideoRecorder
from storage.sqlite_store import DetectionStore


class DetectionThread(QThread):
    frame_processed = Signal(np.ndarray)
    stats_updated = Signal(int, int)
    curve_data = Signal(int, int)
    crossing_signal = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.running = True
        self.mutex = QMutex()
        self.cond = QWaitCondition()
        self.current_frame = None
        self.current_frame_idx = 0
        self.new_frame_available = False

        self.model_path = "models/yolo11n.pt"
        self.fps = 25.0
        self.conf_threshold = 0.55
        self.image_size = 640
        self.tracker_max_age = 20
        self.tracker_n_init = 4
        self.detect_interval = 1

        self.detector = None
        self.tracker = None
        self.counter = RegionCounter()
        self.store = DetectionStore()
        self.recorder = VideoRecorder()

    def set_model(self, model_path):
        self.model_path = model_path

    def set_detection_params(
        self,
        conf_threshold=0.55,
        image_size=640,
        tracker_max_age=20,
        tracker_n_init=4,
        detect_interval=1,
    ):
        self.conf_threshold = conf_threshold
        self.image_size = image_size
        self.tracker_max_age = tracker_max_age
        self.tracker_n_init = tracker_n_init
        self.detect_interval = detect_interval

    def set_region(self, region_norm):
        self.counter.set_region(region_norm)

    def set_db_path(self, db_path):
        self.store.set_db_path(db_path)

    def set_video_writer(self, out_path, width, height):
        self.recorder.open(out_path, self.fps, width, height)

    def load_model(self):
        self.detector = PersonDetector(
            self.model_path,
            conf_threshold=self.conf_threshold,
            image_size=self.image_size,
        )
        self.detector.load()
        self.tracker = PersonTracker(
            max_age=self.tracker_max_age,
            n_init=self.tracker_n_init,
        )

    def run(self):
        self.store.open()
        self.load_model()
        while self.running:
            self.mutex.lock()
            if not self.new_frame_available:
                self.cond.wait(self.mutex)
            if not self.running:
                self.mutex.unlock()
                break
            frame = self.current_frame.copy() if self.current_frame is not None else None
            frame_idx = self.current_frame_idx
            self.new_frame_available = False
            self.mutex.unlock()

            if frame is not None:
                processed = self._detect_and_track(frame, frame_idx)
                self.recorder.write(processed, frame_idx, frame)
                self.frame_processed.emit(processed)

        current_sec = self.current_frame_idx / self.fps if self.fps > 0 else 0
        self.store.close(self.counter.get_active_duration_records(current_sec))
        self.recorder.close()

    def process_frame(self, frame, frame_idx):
        self.mutex.lock()
        self.current_frame = frame
        self.current_frame_idx = frame_idx
        self.new_frame_available = True
        self.cond.wakeOne()
        self.mutex.unlock()

    def _detect_and_track(self, frame, frame_idx):
        if self.detector is None or self.tracker is None:
            return frame

        current_sec = frame_idx / self.fps if self.fps > 0 else 0
        detections = self.detector.detect(frame)
        tracks = self.tracker.update(detections, frame)
        snapshot = self.counter.process_tracks(tracks, frame.shape, current_sec)

        for track_id, enter_sec, leave_sec in snapshot.duration_records:
            self.store.record_duration(track_id, enter_sec, leave_sec)
        self.store.record_second_stats(frame_idx, self.fps, snapshot.active_ids)

        self._draw_overlay(frame, tracks, snapshot.total_crossing, snapshot.inside_count, current_sec)

        self.stats_updated.emit(snapshot.total_crossing, snapshot.inside_count)
        self.curve_data.emit(frame_idx, snapshot.inside_count)
        self.crossing_signal.emit(frame_idx, snapshot.total_crossing)
        return frame

    def _draw_overlay(self, frame, tracks, total_crossing, inside_count, current_sec):
        region_pixels = self.counter.get_region_pixels(frame.shape)
        for track in tracks:
            x1, y1, x2, y2 = track.ltrb
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
            cv2.putText(
                frame,
                f"ID:{track.track_id}",
                (int(x1), int(y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2,
            )

        cv2.putText(frame, f"Time: {self._format_time(current_sec)}", (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(frame, f"Crossing: {total_crossing}", (10, 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(frame, f"Inside: {inside_count}", (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.polylines(frame, [np.array(region_pixels)], isClosed=True, color=(255, 0, 0), thickness=2)

    @staticmethod
    def _format_time(seconds):
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def stop(self):
        self.running = False
        self.mutex.lock()
        self.new_frame_available = True
        self.cond.wakeOne()
        self.mutex.unlock()
        self.wait()
