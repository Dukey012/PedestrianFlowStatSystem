import cv2


class VideoRecorder:
    def __init__(self):
        self.video_writer = None
        self.last_written_idx = -1
        self.last_raw_frame = None

    def open(self, out_path, fps, width, height):
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.video_writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))
        self.last_written_idx = -1
        self.last_raw_frame = None

    def write(self, processed_frame, frame_idx, raw_frame):
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

    def close(self):
        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
