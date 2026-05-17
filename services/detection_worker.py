import cv2
import numpy as np
from PyQt6.QtCore import QMutex, QThread, QWaitCondition, pyqtSignal

from core.exceptions import DetectionPipelineError
from core.counting import RegionCounter
from core.detection import PersonDetector
from core.tracking import PersonTracker
from core.types import TrackSnapshot, TrackState
from services.recorder import VideoRecorder
from storage.sqlite_store import DetectionStore


class DetectionThread(QThread):
    frame_processed = pyqtSignal(int, np.ndarray)
    stats_updated = pyqtSignal(int, int)
    curve_data = pyqtSignal(int, int)
    crossing_signal = pyqtSignal(int, int)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.mutex = QMutex()
        self.cond = QWaitCondition()
        self.input_frames = []
        self.pending_frames = []
        self.current_frame_idx = 0
        self.flush_requested = False
        self.first_frame_idx = None
        self.previous_snapshot = None
        self.store_closed = False
        self.params_saved = False

        self.model_path = "models/yolo11n.pt"
        self.fps = 25.0
        self.conf_threshold = 0.5
        self.image_size = 640
        self.tracker_max_age = 20
        self.tracker_n_init = 4
        self.detect_interval = 1
        self.param_snapshot = None

        self.detector = None
        self.tracker = None
        self.counter = RegionCounter()
        self.store = DetectionStore()
        self.recorder = VideoRecorder()

    def set_model(self, model_path):
        self.model_path = model_path

    def set_detection_params(
        self,
        conf_threshold=0.5,
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

    def set_param_snapshot(self, params):
        self.param_snapshot = dict(params)

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
        try:
            self.store.open()
            self.load_model()
            while True:
                self.mutex.lock()
                while self.running and not self.input_frames and not self.flush_requested:
                    self.cond.wait(self.mutex)
                if not self.running and not self.input_frames and not self.flush_requested:
                    self.mutex.unlock()
                    break
                frames = self.input_frames
                self.input_frames = []
                should_flush = self.flush_requested or not self.running
                self.flush_requested = False
                self.mutex.unlock()

                for frame_idx, frame in frames:
                    self._process_input_frame(frame, frame_idx)
                if should_flush:
                    self._flush_pending_frames()
                if not self.running:
                    break

            current_sec = self._relative_second(self.current_frame_idx)
            self._close_store(current_sec)
        except DetectionPipelineError as exc:
            self.running = False
            self.error_occurred.emit(str(exc))
        except Exception as exc:
            self.running = False
            self.error_occurred.emit(f"检测流程发生未知错误: {exc}")
        finally:
            self._close_store_safely()
            self.recorder.close()

    def process_frame(self, frame, frame_idx):
        self.mutex.lock()
        if not self.running:
            self.mutex.unlock()
            return
        self.current_frame_idx = frame_idx
        self.input_frames.append((frame_idx, frame.copy()))
        self.cond.wakeOne()
        self.mutex.unlock()

    def finish_stream(self):
        self.mutex.lock()
        self.flush_requested = True
        self.cond.wakeOne()
        self.mutex.unlock()

    def _process_input_frame(self, frame, frame_idx):
        self._initialize_timeline(frame_idx)
        self.current_frame_idx = frame_idx
        self.pending_frames.append((frame_idx, frame))

        if not self._should_detect(frame_idx):
            return

        snapshot = self._detect_and_track(frame, frame_idx)
        if self.previous_snapshot is None:
            self._emit_processed_frame(
                frame_idx,
                frame,
                snapshot.tracks,
                snapshot.total_crossing,
                snapshot.inside_count,
            )
        else:
            self._emit_interpolated_frames(self.previous_snapshot, snapshot)

        self.previous_snapshot = snapshot
        self.pending_frames = []

    def _should_detect(self, frame_idx):
        interval = max(1, int(self.detect_interval))
        if self.previous_snapshot is None:
            return True
        return (frame_idx - self.first_frame_idx) % interval == 0

    def _detect_and_track(self, frame, frame_idx):
        if self.detector is None or self.tracker is None:
            return TrackSnapshot(frame_idx, [], 0, 0)

        relative_frame_idx = self._relative_frame_idx(frame_idx)
        current_sec = self._relative_second(frame_idx)
        detections = self.detector.detect(frame)
        tracks = self.tracker.update(detections, frame)
        snapshot = self.counter.process_tracks(tracks, frame.shape, current_sec)

        for track_id, enter_sec, leave_sec in snapshot.duration_records:
            self.store.record_duration(track_id, enter_sec, leave_sec)
        for track_id, crossing_sec in snapshot.crossing_events:
            self.store.record_crossing_event(track_id, relative_frame_idx, crossing_sec)
        self.store.record_second_stats(relative_frame_idx, self.fps, snapshot.active_ids)

        self.stats_updated.emit(snapshot.total_crossing, snapshot.inside_count)
        self.curve_data.emit(frame_idx, snapshot.inside_count)
        self.crossing_signal.emit(frame_idx, snapshot.total_crossing)
        return TrackSnapshot(
            frame_idx=frame_idx,
            tracks=tracks,
            total_crossing=snapshot.total_crossing,
            inside_count=snapshot.inside_count,
        )

    def _emit_interpolated_frames(self, start_snapshot, end_snapshot):
        for frame_idx, frame in self.pending_frames:
            if frame_idx <= start_snapshot.frame_idx:
                continue
            if frame_idx >= end_snapshot.frame_idx:
                tracks = end_snapshot.tracks
                total_crossing = end_snapshot.total_crossing
                inside_count = end_snapshot.inside_count
            else:
                tracks = self._interpolate_tracks(start_snapshot, end_snapshot, frame_idx)
                total_crossing = start_snapshot.total_crossing
                inside_count = start_snapshot.inside_count
            self._emit_processed_frame(frame_idx, frame, tracks, total_crossing, inside_count)

    def _flush_pending_frames(self):
        if not self.pending_frames:
            return
        snapshot = self.previous_snapshot
        if snapshot is None:
            for frame_idx, frame in self.pending_frames:
                self._emit_processed_frame(frame_idx, frame, [], 0, 0)
        else:
            for frame_idx, frame in self.pending_frames:
                if frame_idx <= snapshot.frame_idx:
                    continue
                self._emit_processed_frame(
                    frame_idx,
                    frame,
                    snapshot.tracks,
                    snapshot.total_crossing,
                    snapshot.inside_count,
                )
        self.pending_frames = []

    def _interpolate_tracks(self, start_snapshot, end_snapshot, frame_idx):
        start_tracks = {track.track_id: track for track in start_snapshot.tracks}
        end_tracks = {track.track_id: track for track in end_snapshot.tracks}
        common_ids = start_tracks.keys() & end_tracks.keys()
        span = max(1, end_snapshot.frame_idx - start_snapshot.frame_idx)
        alpha = (frame_idx - start_snapshot.frame_idx) / span

        tracks = []
        for track_id in common_ids:
            start_box = np.array(start_tracks[track_id].ltrb, dtype=np.float32)
            end_box = np.array(end_tracks[track_id].ltrb, dtype=np.float32)
            box = start_box * (1 - alpha) + end_box * alpha
            tracks.append(TrackState(track_id=track_id, ltrb=tuple(float(v) for v in box)))
        return tracks

    def _emit_processed_frame(self, frame_idx, frame, tracks, total_crossing, inside_count):
        processed = frame.copy()
        display_sec = frame_idx / self.fps if self.fps > 0 else 0
        self._draw_overlay(processed, tracks, total_crossing, inside_count, display_sec)
        self.recorder.write(processed, frame_idx)
        self.frame_processed.emit(frame_idx, processed)

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

    def _close_store_safely(self):
        try:
            current_sec = self._relative_second(self.current_frame_idx)
            self._close_store(current_sec)
        except Exception:
            pass

    def _close_store(self, current_sec):
        if self.store_closed:
            return
        self.store.close(self.counter.get_active_duration_records(current_sec))
        self.store_closed = True

    def _initialize_timeline(self, frame_idx):
        if self.first_frame_idx is not None:
            return
        self.first_frame_idx = frame_idx
        if self.param_snapshot and not self.params_saved:
            params = dict(self.param_snapshot)
            params["source_start_frame_idx"] = frame_idx
            params["source_start_second"] = frame_idx / self.fps if self.fps > 0 else 0.0
            self.store.save_detection_params(params)
            self.params_saved = True

    def _relative_frame_idx(self, frame_idx):
        if self.first_frame_idx is None:
            return 0
        return max(0, frame_idx - self.first_frame_idx)

    def _relative_second(self, frame_idx):
        if self.fps <= 0:
            return 0.0
        return self._relative_frame_idx(frame_idx) / self.fps

    @staticmethod
    def _format_time(seconds):
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def stop(self):
        self.mutex.lock()
        self.running = False
        self.input_frames = []
        self.flush_requested = True
        self.cond.wakeOne()
        self.mutex.unlock()
        self.wait()
