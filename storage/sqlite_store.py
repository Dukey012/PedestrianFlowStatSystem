import sqlite3
from pathlib import Path

from core.exceptions import DetectionPipelineError


class DetectionStore:
    def __init__(self):
        self.db_path = None
        self.conn = None
        self.cursor = None
        self.second_ids_buffer = {}
        self.last_recorded_second = -1

    def set_db_path(self, db_path):
        self.db_path = db_path

    def open(self):
        if not self.db_path:
            return
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS second_stats (
                    second INTEGER,
                    inside_count INTEGER,
                    track_ids TEXT
                )
                """
            )
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS person_durations (
                    track_id INTEGER,
                    enter_second REAL,
                    leave_second REAL
                )
                """
            )
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS crossing_events (
                    track_id INTEGER,
                    frame_idx INTEGER,
                    second REAL
                )
                """
            )
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS detection_params (
                    model_name TEXT,
                    conf_threshold REAL,
                    image_size INTEGER,
                    tracker_max_age INTEGER,
                    tracker_n_init INTEGER,
                    detect_interval INTEGER,
                    fps REAL,
                    total_frames INTEGER
                )
                """
            )
            self.conn.commit()
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"数据库初始化失败: {exc}") from exc

    def record_duration(self, track_id, enter_second, leave_second):
        if not self.conn:
            return
        try:
            self.cursor.execute(
                "INSERT INTO person_durations VALUES (?, ?, ?)",
                (track_id, enter_second, leave_second),
            )
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"写入停留时长失败: {exc}") from exc

    def record_crossing_event(self, track_id, frame_idx, second):
        if not self.conn:
            return
        try:
            self.cursor.execute(
                "INSERT INTO crossing_events VALUES (?, ?, ?)",
                (track_id, frame_idx, second),
            )
            self.conn.commit()
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"写入通过事件失败: {exc}") from exc

    def record_second_stats(self, frame_idx, fps, active_ids):
        if fps <= 0 or not self.conn:
            return

        sec = frame_idx / fps
        int_sec = int(sec)
        if self.last_recorded_second == -1:
            self.last_recorded_second = int_sec - 1
        if int_sec not in self.second_ids_buffer:
            self.second_ids_buffer[int_sec] = set()
        self.second_ids_buffer[int_sec].update(active_ids)

        try:
            while self.last_recorded_second < int_sec - 1:
                self.last_recorded_second += 1
                if self.last_recorded_second in self.second_ids_buffer:
                    ids_set = self.second_ids_buffer.pop(self.last_recorded_second)
                    self._insert_second_stats(self.last_recorded_second, ids_set)
                else:
                    self.cursor.execute(
                        "INSERT INTO second_stats VALUES (?, ?, ?)",
                        (self.last_recorded_second, 0, ""),
                    )
            self.conn.commit()
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"写入秒级统计失败: {exc}") from exc

    def save_detection_params(self, params):
        if not self.conn:
            return
        try:
            self.cursor.execute("DELETE FROM detection_params")
            self.cursor.execute(
                "INSERT INTO detection_params VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    params.get("model_name", ""),
                    params.get("conf_threshold", 0.0),
                    params.get("image_size", 0),
                    params.get("tracker_max_age", 0),
                    params.get("tracker_n_init", 0),
                    params.get("detect_interval", 0),
                    params.get("fps", 0.0),
                    params.get("total_frames", 0),
                ),
            )
            self.conn.commit()
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"保存检测参数失败: {exc}") from exc

    def close(self, active_duration_records=None):
        if not self.conn:
            return

        try:
            for record in active_duration_records or []:
                self.record_duration(*record)
            for sec, ids_set in self.second_ids_buffer.items():
                self._insert_second_stats(sec, ids_set)

            self.conn.commit()
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"关闭数据库前写入剩余统计失败: {exc}") from exc
        finally:
            self.conn.close()
            self.conn = None

    def _insert_second_stats(self, second, ids_set):
        inside = len(ids_set)
        ids_str = ",".join(str(track_id) for track_id in sorted(ids_set))
        self.cursor.execute(
            "INSERT INTO second_stats VALUES (?, ?, ?)",
            (second, inside, ids_str),
        )

    @staticmethod
    def load_second_stats(db_path):
        if not db_path or not Path(db_path).exists():
            return []
        try:
            with sqlite3.connect(db_path, timeout=1.0) as conn:
                return conn.execute(
                    "SELECT second, inside_count FROM second_stats ORDER BY second"
                ).fetchall()
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"读取秒级统计失败: {exc}") from exc

    @staticmethod
    def count_crossings_between(db_path, start_sec, end_sec):
        if not db_path or not Path(db_path).exists():
            return 0
        try:
            with sqlite3.connect(db_path, timeout=1.0) as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM crossing_events
                    WHERE second > ? AND second <= ?
                    """,
                    (start_sec, end_sec),
                ).fetchone()
                return int(row[0]) if row else 0
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"读取时段通过事件失败: {exc}") from exc

    @staticmethod
    def load_detection_params(db_path):
        if not db_path or not Path(db_path).exists():
            return None
        try:
            with sqlite3.connect(db_path, timeout=1.0) as conn:
                row = conn.execute(
                    """
                    SELECT model_name, conf_threshold, image_size, tracker_max_age,
                           tracker_n_init, detect_interval, fps, total_frames
                    FROM detection_params
                    LIMIT 1
                    """
                ).fetchone()
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"读取检测参数失败: {exc}") from exc
        if not row:
            return None
        return {
            "model_name": row[0],
            "conf_threshold": row[1],
            "image_size": row[2],
            "tracker_max_age": row[3],
            "tracker_n_init": row[4],
            "detect_interval": row[5],
            "fps": row[6],
            "total_frames": row[7],
        }

    @staticmethod
    def get_replay_stats_at(db_path, current_sec):
        if not db_path or not Path(db_path).exists():
            return 0, 0
        try:
            with sqlite3.connect(db_path, timeout=1.0) as conn:
                crossing_row = conn.execute(
                    "SELECT COUNT(*) FROM crossing_events WHERE second <= ?",
                    (current_sec,),
                ).fetchone()
                inside_row = conn.execute(
                    """
                    SELECT inside_count
                    FROM second_stats
                    WHERE second <= ?
                    ORDER BY second DESC
                    LIMIT 1
                    """,
                    (int(current_sec),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise DetectionPipelineError(f"读取回放统计失败: {exc}") from exc
        total_crossing = int(crossing_row[0]) if crossing_row else 0
        inside_count = int(inside_row[0]) if inside_row else 0
        return total_crossing, inside_count
