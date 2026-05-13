import sys
import os
import cv2
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

from core.exceptions import DetectionPipelineError
from services.detection_worker import DetectionThread
from storage.sqlite_store import DetectionStore
from ui.main_view import setup_ui


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("行人流量统计系统")
        self.setFixedSize(1280, 840)

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
        self.last_processed_frame_idx = -1
        self.last_submitted_frame_idx = -1
        self.detection_stream_finished = False
        self.detection_session_id = 0

        # 进度条更新保护标志
        self.updating_progress = False

        # 检测线程
        self.detector_thread = None
        self.is_detecting = False

        # 统计数据
        self.total_crossing = 0
        self.current_in_region = 0
        self.stats_db_path = None
        self.stats_time_offset_sec = 0.0
        self.stats_time_origin_set = False

        # 曲线数据
        self.curve_frames = []
        self.curve_counts = []

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

    def apply_detection_params(self, params):
        if not params:
            return
        self.model_combo.setCurrentText(str(params["model_name"]))
        self.conf_spin.setValue(float(params["conf_threshold"]))
        self.image_size_combo.setCurrentText(str(int(params["image_size"])))
        self.max_age_spin.setValue(int(params["tracker_max_age"]))
        self.n_init_spin.setValue(int(params["tracker_n_init"]))
        self.detect_interval_spin.setValue(int(params["detect_interval"]))

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
        self.last_processed_frame_idx = -1
        self.last_submitted_frame_idx = -1
        self.detection_stream_finished = False
        self.is_replay = False
        self.btn_detect.setEnabled(True)
        self.set_param_panel_enabled(True)
        self.show_frame_at(0)
        self.btn_play.setEnabled(True)
        self.time_label.setText(f"0:00 / {self.format_time(self.total_frames / self.fps)}")

    def _clear_data(self):
        self.total_crossing = 0
        self.current_in_region = 0
        self.stats_db_path = None
        self.stats_time_offset_sec = 0.0
        self.stats_time_origin_set = False
        self.curve_frames.clear()
        self.curve_counts.clear()
        self.update_stats(0, 0)
        self.clear_span_selection()
        self.update_curve()
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
                self.current_frame_idx = idx
                if self.is_replay:
                    self._update_replay_stats_at(idx)

    def _read_next_frame(self):
        if not self.cap:
            return None, None
        frame_idx = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        ret, frame = self.cap.read()
        if not ret:
            return None, None
        return frame_idx, frame

    def _align_capture_after_current_frame(self):
        if not self.cap:
            return
        next_frame_idx = min(max(self.current_frame_idx + 1, 0), self.total_frames)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, next_frame_idx)

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
        self.timer.start(self._playback_timer_interval())
        if self.is_detecting and (self.detector_thread is None or not self.detector_thread.isRunning()):
            self._launch_detection_thread()
        if self.is_detecting:
            self._pump_detection_frames()

    def pause_video(self):
        self.is_playing = False
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.timer.stop()

    def _playback_timer_interval(self):
        if self.is_detecting:
            return max(10, int(1000 / self.fps)) if self.fps > 0 else 40
        return max(1, int(1000 / (self.fps * self.speed)))

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
        self.last_processed_frame_idx = self.current_frame_idx
        self.last_submitted_frame_idx = self.current_frame_idx
        self.detection_stream_finished = False
        self.stats_time_offset_sec = 0.0
        self.stats_time_origin_set = False
        self.btn_detect.setIcon(self.detect_icon_active)
        self.btn_detect.setToolTip("停止检测")
        self.speed_combo.setEnabled(False)
        self.set_param_panel_enabled(False)
        self.video_label.set_region_enabled(False)
        if self.is_playing:
            self._launch_detection_thread()
            self.timer.setInterval(self._playback_timer_interval())
            self._pump_detection_frames()

    def stop_detection(self):
        if not self.is_detecting:
            return
        self.is_detecting = False
        self.detection_session_id += 1
        self.btn_detect.setChecked(False)
        self.btn_detect.setIcon(self.detect_icon_normal)
        self.btn_detect.setToolTip("检测")
        if self.detector_thread:
            self.detector_thread.stop()
            self.detector_thread = None
        self._align_capture_after_current_frame()
        self.last_submitted_frame_idx = self.last_processed_frame_idx
        self.detection_stream_finished = False
        self.speed_combo.setEnabled(True)
        self.set_param_panel_enabled(not self.is_replay)
        self.video_label.set_region_enabled(True)
        if self.is_playing:
            self.timer.setInterval(self._playback_timer_interval())
        self.current_in_region = 0
        self.update_stats(self.total_crossing, 0)

    def on_detection_error(self, message, session_id=None):
        if session_id is not None and session_id != self.detection_session_id:
            return
        self.detection_session_id += 1
        self.pause_video()
        self.is_detecting = False
        self.btn_detect.setChecked(False)
        self.btn_detect.setIcon(self.detect_icon_normal)
        self.btn_detect.setToolTip("检测")
        if self.detector_thread:
            if self.detector_thread.isRunning():
                self.detector_thread.stop()
            self.detector_thread = None
        self.speed_combo.setEnabled(True)
        self.set_param_panel_enabled(not self.is_replay)
        self.video_label.set_region_enabled(True)
        if self.is_playing:
            self.timer.setInterval(self._playback_timer_interval())
        self.current_in_region = 0
        self.update_stats(self.total_crossing, 0)
        QMessageBox.critical(self, "检测错误", message)

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

        try:
            self._align_capture_after_current_frame()
            self.detection_session_id += 1
            session_id = self.detection_session_id
            self.stats_db_path = db_path
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
            param_snapshot = dict(params)
            param_snapshot["fps"] = self.fps
            param_snapshot["total_frames"] = self.total_frames
            self.detector_thread.set_param_snapshot(param_snapshot)
            self.detector_thread.set_video_writer(
                out_path,
                int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            )
            self.detector_thread.frame_processed.connect(
                lambda frame_idx, frame, sid=session_id: self.on_frame_processed(frame_idx, frame, sid)
            )
            self.detector_thread.stats_updated.connect(
                lambda crossing, inside, sid=session_id: self.on_detection_stats_updated(crossing, inside, sid)
            )
            self.detector_thread.curve_data.connect(
                lambda frame_idx, count, sid=session_id: self.on_curve_data(frame_idx, count, sid)
            )
            self.detector_thread.error_occurred.connect(
                lambda message, sid=session_id: self.on_detection_error(message, sid)
            )
            self.detector_thread.set_region(self.count_region)
            self.detector_thread.start()
            self.last_processed_frame_idx = self.current_frame_idx
            self.last_submitted_frame_idx = self.current_frame_idx
            self.detection_stream_finished = False
        except DetectionPipelineError as exc:
            self.detector_thread = None
            self.on_detection_error(str(exc))
        except Exception as exc:
            self.detector_thread = None
            self.on_detection_error(f"启动检测失败: {exc}")

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
        self.last_processed_frame_idx = -1
        self.last_submitted_frame_idx = -1
        self.detection_stream_finished = False
        self.is_replay = True
        self.btn_detect.setEnabled(False)
        self.speed = 1.0
        self.speed_combo.blockSignals(True)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.blockSignals(False)
        self.btn_play.setEnabled(True)
        matched_db_path = self._match_replay_db(path)
        if matched_db_path:
            try:
                self.stats_db_path = matched_db_path
                self._restore_params_from_db(matched_db_path)
                self._restore_stats_from_db(matched_db_path)
                self.set_param_panel_enabled(False)
            except DetectionPipelineError as exc:
                self.stats_db_path = None
                QMessageBox.warning(self, "提示", str(exc))
        else:
            self.set_param_panel_enabled(False)
            QMessageBox.warning(self, "提示", "未找到对应统计数据库，回放仅显示视频")
        self.show_frame_at(0)

    def _match_replay_db(self, replay_path):
        replay_stem = os.path.splitext(os.path.basename(replay_path))[0]
        if not replay_stem.startswith("output_"):
            return None
        db_name = f"data_{replay_stem[len('output_'):]}.db"
        db_path = os.path.join(os.path.abspath(self.data_dir), db_name)
        return db_path if os.path.exists(db_path) else None

    def _restore_stats_from_db(self, db_path):
        second_stats = DetectionStore.load_second_stats(db_path)
        self.curve_frames = [int(second * self.fps) for second, _ in second_stats]
        self.curve_counts = [inside_count for _, inside_count in second_stats]
        self._update_replay_stats_at(0)
        self.update_curve()

    def _restore_params_from_db(self, db_path):
        params = DetectionStore.load_detection_params(db_path)
        if not params:
            raise DetectionPipelineError("未找到回放视频对应的检测参数")
        self.apply_detection_params(params)

    def _update_replay_stats_at(self, frame_idx):
        if not self.is_replay or not self.stats_db_path or self.fps <= 0:
            return
        current_sec = frame_idx / self.fps
        crossing, inside = DetectionStore.get_replay_stats_at(self.stats_db_path, current_sec)
        self.update_stats(crossing, inside)

    # ================== 帧更新循环 ==================
    def update_frame(self):
        if self.cap and self.is_playing:
            if self.is_detecting and self.detector_thread and self.detector_thread.isRunning():
                self._pump_detection_frames()
                return

            frame_idx, frame = self._read_next_frame()
            if frame is None:
                self.pause_video()
                return

            self.current_frame_idx = frame_idx
            self.set_progress(self.current_frame_idx)
            seconds = self.current_frame_idx / self.fps
            total_seconds = self.total_frames / self.fps
            self.time_label.setText(f"{self.format_time(seconds)} / {self.format_time(total_seconds)}")
            if self.is_replay:
                self._update_replay_stats_at(self.current_frame_idx)
            pix = self.frame_to_pixmap(frame)
            self.video_label.setPixmap(pix)

    def _pump_detection_frames(self):
        if (
            not self.cap
            or not self.is_playing
            or not self.is_detecting
            or not self.detector_thread
            or not self.detector_thread.isRunning()
            or self.detection_stream_finished
        ):
            return

        max_inflight = max(2, self.detect_interval_spin.value() + 1)
        while self.last_submitted_frame_idx - self.last_processed_frame_idx < max_inflight:
            frame_idx, frame = self._read_next_frame()
            if frame is None:
                self.detection_stream_finished = True
                self.detector_thread.finish_stream()
                self.pause_video()
                return
            if not self.stats_time_origin_set:
                self.stats_time_offset_sec = frame_idx / self.fps if self.fps > 0 else 0.0
                self.stats_time_origin_set = True
            self.last_submitted_frame_idx = frame_idx
            self.detector_thread.process_frame(frame, frame_idx)

    def on_frame_processed(self, frame_idx, frame, session_id=None):
        if session_id is not None and session_id != self.detection_session_id:
            return
        if not self.is_detecting:
            return
        if frame_idx < self.last_processed_frame_idx:
            return
        self.last_processed_frame_idx = frame_idx
        self.current_frame_idx = frame_idx
        self.set_progress(self.current_frame_idx)
        seconds = self.current_frame_idx / self.fps
        total_seconds = self.total_frames / self.fps
        self.time_label.setText(f"{self.format_time(seconds)} / {self.format_time(total_seconds)}")
        if hasattr(self, "pos_line"):
            self.pos_line.set_xdata([seconds])
            self.canvas.draw_idle()
        pix = self.frame_to_pixmap(frame)
        self.video_label.setPixmap(pix)
        self._pump_detection_frames()

    def on_detection_stats_updated(self, crossing, inside, session_id):
        if session_id != self.detection_session_id or not self.is_detecting:
            return
        self.update_stats(crossing, inside)

    def update_stats(self, crossing, inside):
        self.total_crossing = crossing
        self.current_in_region = inside
        self.label_crossing.setText(f"累积通过人数: {crossing}")
        self.label_inside.setText(f"区域内当前人数: {inside}")

    def on_curve_data(self, frame_idx, count, session_id=None):
        if session_id is not None and session_id != self.detection_session_id:
            return
        if session_id is not None and not self.is_detecting:
            return
        self.curve_frames.append(frame_idx)
        self.curve_counts.append(count)
        self.update_curve()

    def clear_span_selection(self):
        if hasattr(self, "span_start_edit"):
            self.span_start_edit.clear()
        if hasattr(self, "span_end_edit"):
            self.span_end_edit.clear()
        if getattr(self, "span_patch", None):
            self.span_patch.remove()
            self.span_patch = None

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

    def parse_time_input(self, text):
        text = text.strip()
        if not text:
            raise ValueError("请输入开始时间和结束时间")

        parts = text.split(":")
        try:
            if len(parts) == 1:
                seconds = float(parts[0])
            elif len(parts) == 2:
                minutes = int(parts[0])
                seconds = minutes * 60 + float(parts[1])
            else:
                raise ValueError
        except ValueError as exc:
            raise ValueError("时间格式应为 秒 或 分:秒，例如 12 或 1:25") from exc

        if seconds < 0:
            raise ValueError("时间不能小于 0")
        return seconds

    def on_manual_span_stat(self):
        if self.total_frames <= 0 or self.fps <= 0:
            QMessageBox.warning(self, "提示", "请先打开视频")
            return
        try:
            start_sec = self.parse_time_input(self.span_start_edit.text())
            end_sec = self.parse_time_input(self.span_end_edit.text())
            self.update_span_stats(
                start_sec,
                end_sec,
                update_inputs=True,
                update_chart=True,
                warn_if_out_of_range=True,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))

    def on_span_select(self, xmin, xmax):
        self.update_span_stats(xmin, xmax, update_inputs=True, update_chart=True)

    def update_span_stats(
        self,
        start_sec,
        end_sec,
        update_inputs=True,
        update_chart=True,
        warn_if_out_of_range=False,
    ):
        if self.total_frames <= 0 or self.fps <= 0:
            return

        total_sec = self.total_frames / self.fps
        if start_sec > total_sec or end_sec > total_sec:
            if warn_if_out_of_range:
                QMessageBox.warning(self, "提示", "输入时段不能超过视频总时长")
                return
            start_sec = min(start_sec, total_sec)
            end_sec = min(end_sec, total_sec)
        if start_sec > end_sec:
            start_sec, end_sec = end_sec, start_sec

        if not self.stats_db_path:
            QMessageBox.warning(self, "提示", "未找到当前统计数据库")
            return
        query_start_sec, query_end_sec = self._to_stats_time_range(start_sec, end_sec)
        try:
            interval_crossing = DetectionStore.count_crossings_between(
                self.stats_db_path,
                query_start_sec,
                query_end_sec,
            )
        except DetectionPipelineError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return

        if update_inputs:
            self.span_start_edit.setText(self.format_time(start_sec))
            self.span_end_edit.setText(self.format_time(end_sec))
        if update_chart:
            self.highlight_span(start_sec, end_sec)
        self.label_span_count.setText(f"时段通过: {interval_crossing}")
        self.canvas.draw_idle()

    def _to_stats_time_range(self, start_sec, end_sec):
        if self.is_replay:
            return start_sec, end_sec

        offset = self.stats_time_offset_sec if self.stats_time_origin_set else 0.0
        query_start_sec = start_sec - offset
        query_end_sec = end_sec - offset
        if query_end_sec < 0:
            return 0.0, 0.0
        if query_start_sec <= 0:
            query_start_sec = -1.0
        return query_start_sec, max(0.0, query_end_sec)

    def highlight_span(self, start_sec, end_sec):
        if self.span_patch:
            self.span_patch.remove()
        self.span_patch = self.ax.axvspan(start_sec, end_sec, alpha=0.2, color="red")

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
