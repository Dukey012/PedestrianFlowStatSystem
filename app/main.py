import sys
import os
import cv2
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

from services.detection_worker import DetectionThread
from ui.main_view import setup_ui


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("行人流量统计系统")
        self.setFixedSize(1260, 840)

        # 目录
        self.input_dir = "input"
        self.data_dir = "data"
        self.output_dir = "output"
        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # 视频相关
        self.video_path = None
        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.is_playing = False
        self.speed = 1.0
        self.fps = 25
        self.total_frames = 0
        self.current_frame_idx = 0

        # 进度条更新保护标志
        self.updating_progress = False

        # 检测线程
        self.detector_thread = None
        self.is_detecting = False

        # 统计数据
        self.total_crossing = 0
        self.current_in_region = 0

        # 曲线数据
        self.curve_frames = []
        self.curve_counts = []
        self.crossing_history = []

        # 计数区域
        self.count_region = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

        # 回放状态标志
        self.is_replay = False

        # 调用 UI 构建函数
        setup_ui(self)
        
    # ================== 辅助函数 ==================
    def format_time(self, seconds):
        if seconds < 0:
            return "--.--"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"

    def set_progress(self, idx):
        self.updating_progress = True
        self.progress_slider.setValue(idx)
        self.updating_progress = False

    def get_detection_params(self):
        return {
            "model_name": self.model_combo.currentText(),
            "conf_threshold": self.conf_spin.value(),
            "image_size": int(self.image_size_combo.currentText()),
            "tracker_max_age": self.max_age_spin.value(),
            "tracker_n_init": self.n_init_spin.value(),
            "detect_interval": self.detect_interval_spin.value(),
        }

    def set_param_panel_enabled(self, enabled):
        for widget in (
            self.model_combo,
            self.conf_spin,
            self.image_size_combo,
            self.max_age_spin,
            self.n_init_spin,
            self.detect_interval_spin,
        ):
            widget.setEnabled(enabled)

    # ================== 视频打开 ==================
    def open_video(self):
        if self.is_detecting:
            self.stop_detection()
        if self.is_playing:
            self.pause_video()
        input_dir = os.path.abspath(self.input_dir)
        if not os.path.exists(input_dir):
            os.makedirs(input_dir)
        path, _ = QFileDialog.getOpenFileName(self, "选择视频文件", input_dir,
                                              "视频文件 (*.mp4 *.avi *.mov *.mkv)")
        if not path:
            return
        if self.cap:
            self.cap.release()
        self.video_label.set_region_visible(True)
        self.video_path = path
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            QMessageBox.critical(self, "错误", "无法打开视频文件")
            return
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._clear_data()
        self.video_label.reset_region()
        self.progress_slider.setRange(0, self.total_frames - 1)
        self.set_progress(0)
        self.current_frame_idx = 0
        self.is_replay = False
        self.btn_detect.setEnabled(True)
        self.show_frame_at(0)
        self.btn_play.setEnabled(True)
        self.time_label.setText(f"0:00 / {self.format_time(self.total_frames / self.fps)}")

    def _clear_data(self):
        self.total_crossing = 0
        self.current_in_region = 0
        self.curve_frames.clear()
        self.curve_counts.clear()
        self.crossing_history.clear()
        self.update_stats(0, 0)
        self.update_curve()
        self.label_span_time.setText("时段: --")
        self.label_span_count.setText("时段通过: 0")

    def show_frame_at(self, idx):
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = self.cap.read()
            if ret:
                pix = self.frame_to_pixmap(frame)
                self.video_label.setPixmap(pix)
                seconds = idx / self.fps
                total_seconds = self.total_frames / self.fps
                self.time_label.setText(f"{self.format_time(seconds)} / {self.format_time(total_seconds)}")

    def frame_to_pixmap(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qt_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        return QPixmap.fromImage(qt_img).scaled(
            self.video_label.width(), self.video_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)

    # ================== 播放控制 ==================
    def toggle_play(self):
        if not self.cap:
            return
        if self.is_playing:
            self.pause_video()
        else:
            self.play_video()

    def play_video(self):
        if not self.cap:
            return
        self.is_playing = True
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        interval = max(1, int(1000 / (self.fps * self.speed)))
        self.timer.start(interval)
        if self.is_detecting and (self.detector_thread is None or not self.detector_thread.isRunning()):
            self._launch_detection_thread()

    def pause_video(self):
        self.is_playing = False
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.timer.stop()

    def stop_video(self):
        self.pause_video()
        if self.is_detecting:
            self.stop_detection()
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.set_progress(0)
            self.show_frame_at(0)
        self._clear_data()
        total_sec = self.total_frames / self.fps if self.fps > 0 else 0
        self.time_label.setText(f"0:00 / {self.format_time(total_sec)}")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_detect.setEnabled(not self.is_replay)

    def on_slider_moved(self, value):
        if self.updating_progress:
            return
        if self.is_detecting:
            # 检测状态：回弹并停止播放
            self.pause_video()
            self.set_progress(self.current_frame_idx)   # 回弹到当前帧
        else:
            # 非检测状态：实时预览并暂停播放
            self.pause_video()
            self.show_frame_at(value)

    # ================== 检测开关 ==================
    def toggle_detection(self, checked):
        if self.is_replay:
            QMessageBox.warning(self, "提示", "回放模式下不能使用检测功能")
            self.btn_detect.setChecked(False)
            return
        if checked:
            if not self.cap:
                QMessageBox.warning(self, "提示", "请先打开视频")
                self.btn_detect.setChecked(False)
                return
            self.start_detection()
        else:
            self.stop_detection()

    def start_detection(self):
        if self.is_detecting:
            return
        self.is_detecting = True
        self.btn_detect.setIcon(self.detect_icon_active)
        self.btn_detect.setToolTip("停止检测")
        self.speed_combo.setEnabled(False)
        self.set_param_panel_enabled(False)
        self.video_label.set_region_enabled(False)
        if self.is_playing:
            self._launch_detection_thread()

    def stop_detection(self):
        if not self.is_detecting:
            return
        self.is_detecting = False
        self.btn_detect.setChecked(False)
        self.btn_detect.setIcon(self.detect_icon_normal)
        self.btn_detect.setToolTip("检测")
        if self.detector_thread:
            self.detector_thread.stop()
            self.detector_thread = None
        self.speed_combo.setEnabled(True)
        self.set_param_panel_enabled(True)
        self.video_label.set_region_enabled(True)
        self.current_in_region = 0
        self.update_stats(self.total_crossing, 0)

    def _launch_detection_thread(self):
        if self.detector_thread and self.detector_thread.isRunning():
            return
        video_basename = os.path.splitext(os.path.basename(self.video_path))[0]
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")
        params = self.get_detection_params()
        model_name = params["model_name"]
        
        data_dir = os.path.abspath(self.data_dir)
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, f"data_{video_basename}_{model_name}_{timestamp}.db")
        output_dir = os.path.abspath(self.output_dir)
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"output_{video_basename}_{model_name}_{timestamp}.mp4")

        self.detector_thread = DetectionThread()
        self.detector_thread.set_model(os.path.join("models", f"{model_name}.pt"))
        self.detector_thread.set_detection_params(
            conf_threshold=params["conf_threshold"],
            image_size=params["image_size"],
            tracker_max_age=params["tracker_max_age"],
            tracker_n_init=params["tracker_n_init"],
            detect_interval=params["detect_interval"],
        )
        self.detector_thread.fps = self.fps
        self.detector_thread.set_db_path(db_path)
        self.detector_thread.set_video_writer(
            out_path,
            int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        )
        self.detector_thread.frame_processed.connect(self.on_frame_processed)
        self.detector_thread.stats_updated.connect(self.update_stats)
        self.detector_thread.curve_data.connect(self.on_curve_data)
        self.detector_thread.crossing_signal.connect(self.on_crossing_record)
        self.detector_thread.set_region(self.count_region)
        self.detector_thread.start()

    # ================== 回放 ==================
    def open_replay(self):
        if self.is_detecting:
            self.stop_detection()
        if self.is_playing:
            self.pause_video()
        replay_dir = os.path.abspath(self.output_dir)
        if not os.path.exists(replay_dir):
            os.makedirs(replay_dir)
        path, _ = QFileDialog.getOpenFileName(self, "打开录制视频", replay_dir,
                                              "视频文件 (*.mp4 *.avi *.mov *.mkv)")
        if not path:
            return
        
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            QMessageBox.critical(self, "错误", "无法打开视频文件")
            return
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._clear_data()
        self.video_label.set_region_visible(False)
        self.progress_slider.setRange(0, self.total_frames - 1)
        self.set_progress(0)
        self.current_frame_idx = 0
        self.is_replay = True
        self.btn_detect.setEnabled(False)
        self.speed = 1.0
        self.speed_combo.blockSignals(True)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.blockSignals(False)
        self.btn_play.setEnabled(True)
        self.show_frame_at(0)

    # ================== 帧更新循环 ==================
    def update_frame(self):
        if self.cap and self.is_playing:
            ret, frame = self.cap.read()
            if ret:
                self.current_frame_idx = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                self.set_progress(self.current_frame_idx)
                seconds = self.current_frame_idx / self.fps
                total_seconds = self.total_frames / self.fps
                self.time_label.setText(f"{self.format_time(seconds)} / {self.format_time(total_seconds)}")
                if self.is_detecting and self.detector_thread and self.detector_thread.isRunning():
                    self.detector_thread.process_frame(frame, self.current_frame_idx)
                else:
                    pix = self.frame_to_pixmap(frame)
                    self.video_label.setPixmap(pix)
            else:
                self.pause_video()

    def on_frame_processed(self, frame):
        pix = self.frame_to_pixmap(frame)
        self.video_label.setPixmap(pix)

    def update_stats(self, crossing, inside):
        self.total_crossing = crossing
        self.current_in_region = inside
        self.label_crossing.setText(f"累积通过人数: {crossing}")
        self.label_inside.setText(f"区域内当前人数: {inside}")

    def on_curve_data(self, frame_idx, count):
        self.curve_frames.append(frame_idx)
        self.curve_counts.append(count)
        self.update_curve()

    def on_crossing_record(self, frame_idx, crossing):
        self.crossing_history.append((frame_idx, crossing))

    def update_curve(self):
        total_sec = self.total_frames / self.fps if self.fps > 0 else 10
        if not self.curve_frames:
            self.line.set_data([], [])
            self.pos_line.set_xdata([0])
            self.ax.set_xlim(0, max(10, total_sec))
            self.ax.set_ylim(0, 10)
        else:
            frames = self.curve_frames[:]
            counts = self.curve_counts[:]
            if frames[0] != 0:
                frames.insert(0, 0)
                counts.insert(0, 0)
            times = [f / self.fps for f in frames]
            self.line.set_data(times, counts)
            current_sec = self.current_frame_idx / self.fps
            self.pos_line.set_xdata([current_sec])
            self.ax.set_xlim(0, max(total_sec, 10))
            y_max = max(counts) + 2 if counts else 10
            self.ax.set_ylim(0, y_max)
        self.ax.relim()
        self.ax.autoscale_view(scalex=False, scaley=True)
        self.canvas.draw_idle()

    def on_span_select(self, xmin, xmax):
        start_frame = int(xmin * self.fps)
        end_frame = int(xmax * self.fps)
        if start_frame < 0: start_frame = 0
        if end_frame >= self.total_frames: end_frame = self.total_frames - 1
        crossing_start = 0
        crossing_end = 0
        for f, c in self.crossing_history:
            if f <= start_frame: crossing_start = c
            if f <= end_frame: crossing_end = c
        interval_crossing = crossing_end - crossing_start
        start_time = self.format_time(xmin)
        end_time = self.format_time(xmax)
        self.label_span_time.setText(f"时段: {start_time} - {end_time}")
        self.label_span_count.setText(f"时段通过: {interval_crossing}")
        self.canvas.draw_idle()

    def on_region_changed(self, coords):
        self.count_region = [(coords[0], coords[1]), (coords[2], coords[3]),
                             (coords[4], coords[5]), (coords[6], coords[7])]
        if self.detector_thread:
            self.detector_thread.set_region(self.count_region)

    def change_speed(self, index):
        if self.is_detecting:
            self.speed_combo.blockSignals(True)
            self.speed_combo.setCurrentIndex(1)
            self.speed_combo.blockSignals(False)
            self.speed = 1.0
            return
        self.speed = float(self.speed_combo.currentText().replace('x', ''))
        if self.is_playing:
            self.timer.setInterval(max(1, int(1000 / (self.fps * self.speed))))

    def closeEvent(self, event):
        if self.detector_thread:
            self.detector_thread.stop()
        if self.cap:
            self.cap.release()
        event.accept()


def run():
    app = QApplication(sys.argv)
    window = MainWindow()
    screen = app.primaryScreen().availableGeometry()
    window_rect = window.frameGeometry()
    center_point = screen.center()
    window_rect.moveCenter(center_point)
    window.move(window_rect.topLeft())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
