import unittest

from core.counting import RegionCounter
from core.types import TrackState


FRAME_SHAPE = (100, 100, 3)
INSIDE_TRACK = TrackState(track_id=1, ltrb=(40, 40, 60, 60))
OUTSIDE_TRACK = TrackState(track_id=1, ltrb=(120, 120, 140, 140))


class RegionCounterTests(unittest.TestCase):
    def test_missing_track_expires_without_counting_as_crossing(self):
        counter = RegionCounter(missing_tolerance=2)

        counter.process_tracks([INSIDE_TRACK], FRAME_SHAPE, current_sec=0.0)
        first_missing = counter.process_tracks([], FRAME_SHAPE, current_sec=1.0)
        second_missing = counter.process_tracks([], FRAME_SHAPE, current_sec=2.0)

        self.assertEqual(first_missing.duration_records, [])
        self.assertEqual(second_missing.duration_records, [(1, 0.0, 2.0)])
        self.assertEqual(second_missing.crossing_events, [])
        self.assertEqual(second_missing.total_crossing, 0)
        self.assertEqual(counter.active_durations, {})

    def test_short_missing_gap_does_not_split_duration(self):
        counter = RegionCounter(missing_tolerance=2)

        counter.process_tracks([INSIDE_TRACK], FRAME_SHAPE, current_sec=0.0)
        counter.process_tracks([], FRAME_SHAPE, current_sec=1.0)
        recovered = counter.process_tracks([INSIDE_TRACK], FRAME_SHAPE, current_sec=2.0)

        self.assertEqual(recovered.duration_records, [])
        self.assertEqual(counter.active_durations, {1: 0.0})

    def test_explicit_exit_still_counts_as_crossing(self):
        counter = RegionCounter(missing_tolerance=2)

        counter.process_tracks([INSIDE_TRACK], FRAME_SHAPE, current_sec=0.0)
        exited = counter.process_tracks([OUTSIDE_TRACK], FRAME_SHAPE, current_sec=1.0)

        self.assertEqual(exited.duration_records, [(1, 0.0, 1.0)])
        self.assertEqual(exited.crossing_events, [(1, 1.0)])
        self.assertEqual(exited.total_crossing, 1)


if __name__ == "__main__":
    unittest.main()
