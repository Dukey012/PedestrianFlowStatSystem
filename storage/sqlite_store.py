import sqlite3


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
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS second_stats
                               (second INTEGER, inside_count INTEGER, track_ids TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS person_durations
                               (track_id INTEGER, enter_second REAL, leave_second REAL)''')
        self.conn.commit()

    def record_duration(self, track_id, enter_second, leave_second):
        if not self.conn:
            return
        self.cursor.execute(
            "INSERT INTO person_durations VALUES (?, ?, ?)",
            (track_id, enter_second, leave_second),
        )

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

    def close(self, active_duration_records=None):
        if not self.conn:
            return

        for record in active_duration_records or []:
            self.record_duration(*record)
        for sec, ids_set in self.second_ids_buffer.items():
            self._insert_second_stats(sec, ids_set)

        self.conn.commit()
        self.conn.close()
        self.conn = None

    def _insert_second_stats(self, second, ids_set):
        inside = len(ids_set)
        ids_str = ','.join(str(track_id) for track_id in sorted(ids_set))
        self.cursor.execute(
            "INSERT INTO second_stats VALUES (?, ?, ?)",
            (second, inside, ids_str),
        )
