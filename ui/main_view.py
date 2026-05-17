from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector

from app.config import (
    DEFAULT_CONF_THRESHOLD,
    DEFAULT_DETECT_INTERVAL,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_MODEL,
    DEFAULT_TRACKER_MAX_AGE,
    DEFAULT_TRACKER_N_INIT,
    IMAGE_SIZE_OPTIONS,
    MODEL_OPTIONS,
)
from ui.video_label import VideoLabel


def setup_ui(mw):
    central = QWidget()
    mw.setCentralWidget(central)
    main_layout = QVBoxLayout(central)
    main_layout.setContentsMargins(10, 10, 10, 10)
    main_layout.setSpacing(8)

    # 顶部区域
    top_layout = QHBoxLayout()
    top_layout.setSpacing(0)

    # 视频显示标签
    mw.video_label = VideoLabel()
    mw.video_label.setFixedSize(860, 540)
    mw.video_label.region_changed.connect(mw.on_region_changed)
    top_layout.addStretch(1)
    top_layout.addWidget(mw.video_label)
    top_layout.addStretch(1)

    main_layout.addLayout(top_layout)

    # 控制栏
    control_layout = QHBoxLayout()
    control_layout.setSpacing(6)
    control_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

    btn_size = QSize(50, 40)
    icon_size = QSize(24, 24)

    # 打开视频按钮
    mw.btn_open = QPushButton()
    mw.btn_open.setIcon(mw.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
    mw.btn_open.setIconSize(icon_size)
    mw.btn_open.setFixedSize(btn_size)
    mw.btn_open.setToolTip("打开视频[F]")
    mw.btn_open.clicked.connect(mw.open_video)
    control_layout.addWidget(mw.btn_open)

    # 回放按钮
    mw.btn_replay = QPushButton()
    mw.btn_replay.setIcon(mw.style().standardIcon(QStyle.StandardPixmap.SP_MediaSeekBackward))
    mw.btn_replay.setIconSize(QSize(30, 30))
    mw.btn_replay.setFixedSize(btn_size)
    mw.btn_replay.setToolTip("回放[R]")
    mw.btn_replay.clicked.connect(mw.open_replay)
    control_layout.addWidget(mw.btn_replay)

    # 播放/暂停按钮
    mw.btn_play = QPushButton()
    mw.btn_play.setIcon(mw.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
    mw.btn_play.setIconSize(QSize(28, 28))
    mw.btn_play.setFixedSize(btn_size)
    mw.btn_play.setToolTip("播放/暂停[Space]")
    mw.btn_play.clicked.connect(mw.toggle_play)
    mw.btn_play.setEnabled(False)
    control_layout.addWidget(mw.btn_play)

    # 检测按钮
    mw.btn_detect = QPushButton()
    mw.btn_detect.setCheckable(True)
    normal_icon = create_concentric_icon(22, QColor(0, 0, 0))
    active_icon = create_concentric_icon(22, QColor(255, 0, 0))
    mw.btn_detect.setIcon(normal_icon)
    mw.btn_detect.setIconSize(icon_size)
    mw.btn_detect.setFixedSize(btn_size)
    mw.btn_detect.setToolTip("检测[C]")
    mw.btn_detect.clicked.connect(mw.toggle_detection)
    control_layout.addWidget(mw.btn_detect)

    mw.detect_icon_normal = normal_icon
    mw.detect_icon_active = active_icon

    # 重置按钮
    mw.btn_reset = QPushButton()
    mw.btn_reset.setIcon(mw.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
    mw.btn_reset.setIconSize(QSize(22, 22))
    mw.btn_reset.setFixedSize(btn_size)
    mw.btn_reset.setToolTip("重置[D]")
    mw.btn_reset.clicked.connect(mw.reset_video)
    control_layout.addWidget(mw.btn_reset)

    # 倍速选择
    control_layout.addWidget(QLabel("倍速:"))
    mw.speed_combo = QComboBox()
    mw.speed_combo.addItems(["0.5x", "1.0x", "1.25x", "1.5x", "2.0x", "3.0x"])
    mw.speed_combo.setCurrentIndex(1)
    mw.speed_combo.setFixedSize(60, 24)
    mw.speed_combo.currentIndexChanged.connect(mw.change_speed)
    control_layout.addWidget(mw.speed_combo)

    # 进度条
    mw.progress_slider = QSlider(Qt.Orientation.Horizontal)
    mw.progress_slider.setFixedHeight(20)
    mw.progress_slider.sliderMoved.connect(mw.on_slider_moved)
    control_layout.addWidget(mw.progress_slider, stretch=1)

    # 时间标签
    mw.time_label = QLabel("--.-- / --.--")
    mw.time_label.setFixedWidth(70)
    mw.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    control_layout.addWidget(mw.time_label)
    right_margin = 15
    control_layout.addSpacerItem(QSpacerItem(right_margin, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))

    main_layout.addLayout(control_layout)

    # 底部布局（参数区 + 计数区 + 图表区）
    bottom_layout = QHBoxLayout()
    bottom_layout.setSpacing(0)

    # 左侧参数区
    param_panel = QVBoxLayout()
    param_panel.setContentsMargins(0, 0, 0, 0)
    param_panel.setSpacing(0)

    mw.model_combo = QComboBox()
    mw.model_combo.addItems(MODEL_OPTIONS)
    mw.model_combo.setCurrentText(DEFAULT_MODEL)
    mw.model_combo.setFixedSize(96, 24)
    param_panel.addWidget(create_param_row("模型选择", mw.model_combo))

    mw.conf_spin = QDoubleSpinBox()
    mw.conf_spin.setRange(0.10, 0.95)
    mw.conf_spin.setSingleStep(0.05)
    mw.conf_spin.setDecimals(2)
    mw.conf_spin.setValue(DEFAULT_CONF_THRESHOLD)
    mw.conf_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    mw.conf_spin.setToolTip("允许范围: 0.10 - 0.95")
    mw.conf_spin.setFixedWidth(96)
    param_panel.addWidget(create_param_row("置信度阈值", mw.conf_spin))

    mw.image_size_combo = QComboBox()
    mw.image_size_combo.addItems([str(size) for size in IMAGE_SIZE_OPTIONS])
    mw.image_size_combo.setCurrentText(str(DEFAULT_IMAGE_SIZE))
    mw.image_size_combo.setFixedSize(96, 24)
    param_panel.addWidget(create_param_row("检测尺寸", mw.image_size_combo))

    mw.max_age_spin = QSpinBox()
    mw.max_age_spin.setRange(10, 300)
    mw.max_age_spin.setValue(DEFAULT_TRACKER_MAX_AGE)
    mw.max_age_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    mw.max_age_spin.setToolTip("允许范围: 10 - 300")
    mw.max_age_spin.setFixedWidth(96)
    param_panel.addWidget(create_param_row("最大丢失帧数", mw.max_age_spin))

    mw.n_init_spin = QSpinBox()
    mw.n_init_spin.setRange(1, 30)
    mw.n_init_spin.setValue(DEFAULT_TRACKER_N_INIT)
    mw.n_init_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    mw.n_init_spin.setToolTip("允许范围: 1 - 30")
    mw.n_init_spin.setFixedWidth(96)
    param_panel.addWidget(create_param_row("确认所需帧数", mw.n_init_spin))

    mw.detect_interval_spin = QSpinBox()
    mw.detect_interval_spin.setRange(1, 10)
    mw.detect_interval_spin.setValue(DEFAULT_DETECT_INTERVAL)
    mw.detect_interval_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    mw.detect_interval_spin.setToolTip("允许范围: 1 - 10")
    mw.detect_interval_spin.setFixedWidth(96)
    param_panel.addWidget(create_param_row("抽帧间隔", mw.detect_interval_spin))
    param_panel.addStretch()

    param_widget = QWidget()
    param_widget.setLayout(param_panel)
    param_widget.setFixedWidth(230)
    bottom_layout.addWidget(param_widget)
    bottom_layout.addSpacerItem(QSpacerItem(40, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))

    # 中部计数区
    stats_panel = QVBoxLayout()
    stats_panel.setContentsMargins(0, 0, 0, 0)
    stats_panel.setSpacing(0)
    mw.label_crossing = QLabel("累积通过人数: 0")
    mw.label_inside = QLabel("区域内当前人数: 0")
    mw.label_span_count = QLabel("时段通过: 0")
    stats_panel.addWidget(create_fixed_stats_row(mw.label_crossing))
    stats_panel.addWidget(create_fixed_stats_row(mw.label_inside))
    stats_panel.addWidget(create_empty_stats_row())
    stats_panel.addWidget(create_span_input_row(mw))
    stats_panel.addWidget(create_fixed_stats_row(mw.label_span_count))
    stats_panel.addStretch()

    stats_widget = QWidget()
    stats_widget.setLayout(stats_panel)
    stats_widget.setFixedWidth(230)

    bottom_layout.addWidget(stats_widget)
    bottom_layout.addSpacerItem(QSpacerItem(6, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))

    # 右侧图表区
    curve_container = QHBoxLayout()
    curve_container.setContentsMargins(0, 0, 0, 0)

    mw.figure = Figure(figsize=(7, 1.8), dpi=100)
    bg_color = mw.palette().color(QPalette.ColorRole.Window).name()
    mw.figure.patch.set_facecolor(bg_color)
    mw.canvas = FigureCanvas(mw.figure)
    mw.canvas.setStyleSheet(f"background-color: {bg_color}; border: none;")
    curve_container.addWidget(mw.canvas, stretch=1)

    bottom_layout.addLayout(curve_container, stretch=1)
    right_graph_margin = 70
    curve_container.addSpacerItem(QSpacerItem(right_graph_margin, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
    main_layout.addLayout(bottom_layout)

    # 图表设置
    mw.ax = mw.figure.add_subplot(111)
    mw.ax.set_facecolor('white')
    mw.ax.tick_params(colors='black')
    mw.ax.set_ylabel('区\n域\n内\n人\n数', color='black', rotation=0,
                     labelpad=15, va='center', ha='right')
    mw.ax.set_xlim(0, 10)
    mw.ax.set_ylim(0, 10)
    mw.line, = mw.ax.plot([], [], color='#0072bd', linewidth=1.5)
    mw.pos_line = mw.ax.axvline(x=0, color='red', linewidth=1, linestyle='--')
    mw.figure.subplots_adjust(left=0.11, right=0.975, top=0.85, bottom=0.25)

    mw.span = SpanSelector(mw.ax, mw.on_span_select, 'horizontal',
                           useblit=True, props=dict(alpha=0.2, facecolor='red'))
    mw.info_text = mw.ax.text(0.5, 0.95, "", transform=mw.ax.transAxes,
                              ha='center', va='top', fontsize=9, color='red',
                              bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))
    mw.span_patch = None


def create_span_input_row(mw):
    row_widget = QWidget()
    row_widget.setFixedHeight(36)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    input_height = 25
    button_height = 30

    row.addWidget(QLabel("时段"))

    mw.span_start_edit = QLineEdit()
    mw.span_start_edit.setPlaceholderText("开始")
    mw.span_start_edit.setFixedSize(48, input_height)
    mw.span_start_edit.returnPressed.connect(mw.on_manual_span_stat)
    row.addWidget(mw.span_start_edit)

    row.addWidget(QLabel("-"))

    mw.span_end_edit = QLineEdit()
    mw.span_end_edit.setPlaceholderText("结束")
    mw.span_end_edit.setFixedSize(48, input_height)
    mw.span_end_edit.returnPressed.connect(mw.on_manual_span_stat)
    row.addWidget(mw.span_end_edit)

    mw.btn_span_stat = QPushButton("统计")
    mw.btn_span_stat.setFixedSize(42, button_height)
    mw.btn_span_stat.setToolTip("[S]")
    mw.btn_span_stat.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    mw.btn_span_stat.clicked.connect(mw.on_manual_span_stat)
    row.addWidget(mw.btn_span_stat)
    row.addStretch()
    row_widget.setLayout(row)
    return row_widget


def create_fixed_stats_row(widget):
    row_widget = QWidget()
    row_widget.setFixedHeight(36)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(widget)
    row.addStretch()
    row_widget.setLayout(row)
    return row_widget


def create_empty_stats_row():
    row_widget = QWidget()
    row_widget.setFixedHeight(36)
    return row_widget

def create_param_row(label_text, editor):
    row_widget = QWidget()
    row_widget.setFixedHeight(36)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    label = QLabel(label_text)
    label.setFixedWidth(110)
    row.addWidget(label)
    row.addWidget(editor)
    row.addStretch()
    row_widget.setLayout(row)
    return row_widget


def create_concentric_icon(size=20, color=QColor(0, 0, 0)):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, 2.7)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    outer_r = size / 2 - 2
    painter.drawEllipse(QPointF(size / 2, size / 2), outer_r, outer_r)
    inner_r = outer_r // 2
    painter.drawEllipse(QPointF(size / 2, size / 2), inner_r, inner_r)

    painter.end()
    return QIcon(pixmap)
