import tempfile
import unittest
from pathlib import Path

from storage.sqlite_store import DetectionStore


class DetectionStoreReplayTests(unittest.TestCase):
    def test_replay_inside_count_uses_active_duration_intervals(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "stats.db"
            store = DetectionStore()
            store.set_db_path(str(db_path))
            store.open()
            store.record_duration(1, 10.0, 13.0)
            store.record_duration(2, 12.0, 12.8)
            store.record_duration(3, 12.7, 14.0)
            store.close()

            crossing, inside = DetectionStore.get_replay_stats_at(str(db_path), 12.55)

            self.assertEqual(crossing, 0)
            self.assertEqual(inside, 2)

    def test_replay_inside_count_excludes_people_who_have_already_left(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "stats.db"
            store = DetectionStore()
            store.set_db_path(str(db_path))
            store.open()
            store.record_duration(1, 10.0, 12.55)
            store.record_duration(2, 11.0, 13.0)
            store.close()

            crossing, inside = DetectionStore.get_replay_stats_at(str(db_path), 12.55)

            self.assertEqual(crossing, 0)
            self.assertEqual(inside, 1)

    def test_replay_curve_uses_active_counts_at_each_whole_second(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "stats.db"
            store = DetectionStore()
            store.set_db_path(str(db_path))
            store.open()
            store.record_duration(1, 0.2, 2.0)
            store.record_duration(2, 1.0, 3.4)
            store.record_duration(3, 2.6, 4.0)
            store.close()

            curve_stats = DetectionStore.build_replay_curve_stats(str(db_path), 4.8)

            self.assertEqual(curve_stats, [(0, 0), (1, 2), (2, 1), (3, 2), (4, 0)])


if __name__ == "__main__":
    unittest.main()
