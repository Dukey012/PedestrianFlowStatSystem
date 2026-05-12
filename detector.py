import cv2
import sqlite3
import numpy as np
from ultralytics import YOLO
from deep_sort_realtime.deepsort_tracker import DeepSort
from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition


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

        self.model = None
        self.tracker = None
        self.model_path = "models/yolo11n.pt"
        self.fps = 25.0
        self.db_path = None

        self.region_norm = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.track_entered = {}
        self.total_crossing = 0
        self.active_ids_in_region = set()

        # 数据库
        self.conn = None
        self.cursor = None
        self.second_ids_buffer = {}
        self.last_recorded_second = -1
        self.active_durations = {}

        # 录制器 + 补帧控制
        self.video_writer = None
        self.last_written_idx = -1
        self.last_raw_frame = None

    def set_model(self, model_path):
        self.model_path = model_path

    def set_region(self, region_norm):
        self.region_norm = region_norm

    def set_db_path(self, db_path):
        self.db_path = db_path

    def set_video_writer(self, out_path, width, height):
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.video_writer = cv2.VideoWriter(out_path, fourcc, self.fps, (width, height))
        self.last_written_idx = -1
        self.last_raw_frame = None

    def _init_db(self):
        if not self.db_path:
            return
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS second_stats
                               (second INTEGER, inside_count INTEGER, track_ids TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS person_durations
                               (track_id INTEGER, enter_second REAL, leave_second REAL)''')
        self.conn.commit()

    def load_model(self):
        self.model = YOLO(self.model_path)
        self.model.classes = [0]
        if self.tracker is None:
            self.tracker = DeepSort(max_age=20, n_init=4)

    def run(self):
        self._init_db()
        self.load_model()
        while self.running:
            self.mutex.lock()
            if not self.new_frame_available:
                self.cond.wait(self.mutex)
            if not self.running:
                self.mutex.unlock()
                break
            frame = self.current_frame.copy() if self.current_frame is not None else None
            fidx = self.current_frame_idx
            self.new_frame_available = False
            self.mutex.unlock()

            if frame is not None:
                processed = self._detect_and_track(frame, fidx)
                self._write_frame_with_gap_filling(processed, fidx, frame)
                self._record_db(fidx)
                self.frame_processed.emit(processed)
        self._close_db()
        if self.video_writer:
            self.video_writer.release()

    def process_frame(self, frame, frame_idx):
        self.mutex.lock()
        self.current_frame = frame
        self.current_frame_idx = frame_idx
        self.new_frame_available = True
        self.cond.wakeOne()
        self.mutex.unlock()

    def _write_frame_with_gap_filling(self, processed_frame, frame_idx, raw_frame):
        if self.video_writer is None:
            return
        if self.last_written_idx < 0:
            self.last_written_idx = frame_idx
            self.last_raw_frame = raw_frame.copy()
            self.video_writer.write(processed_frame)
            return
        gap = frame_idx - self.last_written_idx
        if gap > 1:
            for _ in range(gap - 1):
                self.video_writer.write(self.last_raw_frame)
        self.video_writer.write(processed_frame)
        self.last_written_idx = frame_idx
        self.last_raw_frame = raw_frame.copy()

    def point_in_region(self, x, y, region_pixels):
        poly = np.array(region_pixels, dtype=np.float32)
        return cv2.pointPolygonTest(poly, (x, y), False) >= 0

    def _detect_and_track(self, frame, frame_idx):
        if self.model is None or self.tracker is None:
            return frame

        h, w = frame.shape[:2]
        region_pixels = [(int(p[0] * w), int(p[1] * h)) for p in self.region_norm]

        results = self.model(frame, imgsz=640, verbose=False)[0]

        detections = []
        for box in results.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = box.conf[0].item()
            if conf > 0.55:
                detections.append(([x1, y1, x2 - x1, y2 - y1], conf, 0))

        tracks = self.tracker.update_tracks(detections, frame=frame)

        current_ids_in_region = set()
        current_sec = frame_idx / self.fps if self.fps > 0 else 0

        for track in tracks:
            if not track.is_confirmed():
                continue
            track_id = track.track_id
            ltrb = track.to_ltrb()
            cx = (ltrb[0] + ltrb[2]) / 2
            cy = (ltrb[1] + ltrb[3]) / 2
            inside = self.point_in_region(cx, cy, region_pixels)

            if inside:
                current_ids_in_region.add(track_id)
                if track_id not in self.track_entered:
                    self.track_entered[track_id] = True
                if track_id not in self.active_durations:
                    self.active_durations[track_id] = current_sec
            else:
                if track_id in self.track_entered:
                    del self.track_entered[track_id]
                    self.total_crossing += 1
                if track_id in self.active_durations:
                    enter_sec = self.active_durations.pop(track_id)
                    self.cursor.execute("INSERT INTO person_durations VALUES (?, ?, ?)",
                                        (track_id, enter_sec, current_sec))

            cv2.rectangle(frame, (int(ltrb[0]), int(ltrb[1])),
                          (int(ltrb[2]), int(ltrb[3])), (0, 255, 0), 2)
            cv2.putText(frame, f"ID:{track_id}", (int(ltrb[0]), int(ltrb[1] - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        self.active_ids_in_region = current_ids_in_region

        cv2.putText(frame, f"Time: {self._format_time(current_sec)}", (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(frame, f"Crossing: {self.total_crossing}", (10, 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(frame, f"Inside: {len(current_ids_in_region)}", (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.polylines(frame, [np.array(region_pixels)], isClosed=True, color=(255, 0, 0), thickness=2)

        self.stats_updated.emit(self.total_crossing, len(current_ids_in_region))
        self.curve_data.emit(frame_idx, len(current_ids_in_region))
        self.crossing_signal.emit(frame_idx, self.total_crossing)
        return frame

    def _format_time(self, seconds):
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"

    def _record_db(self, frame_idx):
        if self.fps <= 0 or not self.conn:
            return
        sec = frame_idx / self.fps
        int_sec = int(sec)
        # 初始化起始秒，跳过检测开始前的数据
        if self.last_recorded_second == -1:
            self.last_recorded_second = int_sec - 1
        if int_sec not in self.second_ids_buffer:
            self.second_ids_buffer[int_sec] = set()
        self.second_ids_buffer[int_sec].update(self.active_ids_in_region)

        while self.last_recorded_second < int_sec - 1:
            self.last_recorded_second += 1
            if self.last_recorded_second in self.second_ids_buffer:
                ids_set = self.second_ids_buffer.pop(self.last_recorded_second)
                inside = len(ids_set)
                ids_str = ','.join(str(tid) for tid in sorted(ids_set))
                self.cursor.execute("INSERT INTO second_stats VALUES (?, ?, ?)",
                                    (self.last_recorded_second, inside, ids_str))
            else:
                self.cursor.execute("INSERT INTO second_stats VALUES (?, ?, ?)",
                                    (self.last_recorded_second, 0, ""))
        self.conn.commit()

    def _close_db(self):
        if not self.conn:
            return
        current_sec = self.current_frame_idx / self.fps if self.fps > 0 else 0
        for tid, enter_sec in self.active_durations.items():
            self.cursor.execute("INSERT INTO person_durations VALUES (?, ?, ?)",
                                (tid, enter_sec, current_sec))
        for sec, ids_set in self.second_ids_buffer.items():
            self.cursor.execute("INSERT INTO second_stats VALUES (?, ?, ?)",
                                (sec, len(ids_set), ','.join(str(tid) for tid in sorted(ids_set))))
        self.conn.commit()
        self.conn.close()

    def stop(self):
        self.running = False
        self.mutex.lock()
        self.new_frame_available = True
        self.cond.wakeOne()
        self.mutex.unlock()
        self.wait()