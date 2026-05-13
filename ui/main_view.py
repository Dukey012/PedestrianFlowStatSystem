from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

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

    # ------------------ 顶部区域 ------------------
    top_layout = QHBoxLayout()
    top_layout.setSpacing(0)

    top_layout.addSpacerItem(QSpacerItem(130, 0, QSizePolicy.Fixed, QSizePolicy.Minimum))

    # 视频显示标签
    mw.video_label = VideoLabel()
    mw.video_label.setFixedSize(860, 540)
    mw.video_label.region_changed.connect(mw.on_region_changed)
    top_layout.addWidget(mw.video_label)

    top_layout.addStretch(1)

    main_layout.addLayout(top_layout)

    # ------------------ 控制栏 ------------------
    control_layout = QHBoxLayout()
    control_layout.setSpacing(6)
    control_layout.setAlignment(Qt.AlignLeft)

    btn_size = QSize(50, 40)
    icon_size = QSize(24, 24)

    # 打开视频按钮
    mw.btn_open = QPushButton()
    mw.btn_open.setIcon(mw.style().standardIcon(QStyle.SP_DialogOpenButton))
    mw.btn_open.setIconSize(icon_size)
    mw.btn_open.setFixedSize(btn_size)
    mw.btn_open.setToolTip("打开视频")
    mw.btn_open.clicked.connect(mw.open_video)
    control_layout.addWidget(mw.btn_open)

    # 回放按钮
    mw.btn_replay = QPushButton()
    mw.btn_replay.setIcon(mw.style().standardIcon(QStyle.SP_BrowserReload))
    mw.btn_replay.setIconSize(icon_size)
    mw.btn_replay.setFixedSize(btn_size)
    mw.btn_replay.setToolTip("回放")
    mw.btn_replay.clicked.connect(mw.open_replay)
    control_layout.addWidget(mw.btn_replay)

    # 播放/暂停按钮
    mw.btn_play = QPushButton()
    mw.btn_play.setIcon(mw.style().standardIcon(QStyle.SP_MediaPlay))
    mw.btn_play.setIconSize(icon_size)
    mw.btn_play.setFixedSize(btn_size)
    mw.btn_play.setToolTip("播放/暂停")
    mw.btn_play.clicked.connect(mw.toggle_play)
    mw.btn_play.setEnabled(False)
    control_layout.addWidget(mw.btn_play)

    # 检测按钮
    mw.btn_detect = QPushButton()
    mw.btn_detect.setCheckable(True)
    normal_icon = create_concentric_icon(20, QColor(0, 0, 0))
    active_icon = create_concentric_icon(20, QColor(255, 0, 0))
    mw.btn_detect.setIcon(normal_icon)
    mw.btn_detect.setIconSize(QSize(20, 20))
    mw.btn_detect.setFixedSize(btn_size)
    mw.btn_detect.setToolTip("检测")
    mw.btn_detect.clicked.connect(mw.toggle_detection)
    control_layout.addWidget(mw.btn_detect)

    mw.detect_icon_normal = normal_icon
    mw.detect_icon_active = active_icon

    # 重置按钮
    mw.btn_stop = QPushButton()
    mw.btn_stop.setIcon(mw.style().standardIcon(QStyle.SP_MediaStop))
    mw.btn_stop.setIconSize(icon_size)
    mw.btn_stop.setFixedSize(btn_size)
    mw.btn_stop.setToolTip("重置")
    mw.btn_stop.clicked.connect(mw.stop_video)
    control_layout.addWidget(mw.btn_stop)

    # 倍速选择
    control_layout.addWidget(QLabel("倍速:"))
    mw.speed_combo = QComboBox()
    mw.speed_combo.addItems(["0.5x", "1.0x", "1.25x", "1.5x", "2.0x", "3.0x"])
    mw.speed_combo.setCurrentIndex(1)
    mw.speed_combo.setFixedWidth(80)
    mw.speed_combo.currentIndexChanged.connect(mw.change_speed)
    control_layout.addWidget(mw.speed_combo)

    # 进度条
    mw.progress_slider = QSlider(Qt.Horizontal)
    mw.progress_slider.setFixedHeight(20)
    mw.progress_slider.sliderMoved.connect(mw.on_slider_moved)
    control_layout.addWidget(mw.progress_slider, stretch=1)

    # 时间标签
    mw.time_label = QLabel("--.-- / --.--")
    mw.time_label.setFixedWidth(70)
    mw.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    control_layout.addWidget(mw.time_label)
    right_margin = 15
    control_layout.addSpacerItem(QSpacerItem(right_margin, 0, QSizePolicy.Fixed, QSizePolicy.Minimum))

    main_layout.addLayout(control_layout)

    # ------------------ 底部布局（参数面板 + 统计面板 + 曲线图） ------------------
    bottom_layout = QHBoxLayout()
    bottom_layout.setSpacing(0)

    # 左侧参数面板
    param_panel = QVBoxLayout()
    param_panel.setContentsMargins(0, 8, 0, 0)
    param_panel.setSpacing(6)

    mw.model_combo = QComboBox()
    mw.model_combo.addItems(MODEL_OPTIONS)
    mw.model_combo.setCurrentText(DEFAULT_MODEL)
    mw.model_combo.setFixedWidth(96)
    param_panel.addLayout(create_param_row("模型选择", mw.model_combo))

    mw.conf_spin = QDoubleSpinBox()
    mw.conf_spin.setRange(0.10, 0.95)
    mw.conf_spin.setSingleStep(0.05)
    mw.conf_spin.setDecimals(2)
    mw.conf_spin.setValue(DEFAULT_CONF_THRESHOLD)
    mw.conf_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    mw.conf_spin.setToolTip("允许范围: 0.10 - 0.95")
    mw.conf_spin.setFixedWidth(96)
    param_panel.addLayout(create_param_row("置信度阈值", mw.conf_spin))

    mw.image_size_combo = QComboBox()
    mw.image_size_combo.addItems([str(size) for size in IMAGE_SIZE_OPTIONS])
    mw.image_size_combo.setCurrentText(str(DEFAULT_IMAGE_SIZE))
    mw.image_size_combo.setFixedWidth(96)
    param_panel.addLayout(create_param_row("检测尺寸", mw.image_size_combo))

    mw.max_age_spin = QSpinBox()
    mw.max_age_spin.setRange(1, 300)
    mw.max_age_spin.setValue(DEFAULT_TRACKER_MAX_AGE)
    mw.max_age_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    mw.max_age_spin.setToolTip("允许范围: 1 - 300")
    mw.max_age_spin.setFixedWidth(96)
    param_panel.addLayout(create_param_row("最大丢失帧数", mw.max_age_spin))

    mw.n_init_spin = QSpinBox()
    mw.n_init_spin.setRange(1, 30)
    mw.n_init_spin.setValue(DEFAULT_TRACKER_N_INIT)
    mw.n_init_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    mw.n_init_spin.setToolTip("允许范围: 1 - 30")
    mw.n_init_spin.setFixedWidth(96)
    param_panel.addLayout(create_param_row("确认所需帧数", mw.n_init_spin))

    mw.detect_interval_spin = QSpinBox()
    mw.detect_interval_spin.setRange(1, 30)
    mw.detect_interval_spin.setValue(DEFAULT_DETECT_INTERVAL)
    mw.detect_interval_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    mw.detect_interval_spin.setToolTip("允许范围: 1 - 30")
    mw.detect_interval_spin.setFixedWidth(96)
    param_panel.addLayout(create_param_row("抽帧间隔", mw.detect_interval_spin))
    param_panel.addStretch()

    param_widget = QWidget()
    param_widget.setLayout(param_panel)
    param_widget.setFixedWidth(230)
    bottom_layout.addWidget(param_widget)
    bottom_layout.addSpacerItem(QSpacerItem(64, 0, QSizePolicy.Fixed, QSizePolicy.Minimum))

    # 中部统计面板
    stats_panel = QVBoxLayout()
    stats_panel.setContentsMargins(0, 20, 0, 0)
    mw.label_crossing = QLabel("累积通过人数: 0")
    mw.label_inside = QLabel("区域内当前人数: 0")
    mw.label_span_time = QLabel("时段: --")
    mw.label_span_count = QLabel("时段通过: 0")
    stats_panel.addWidget(mw.label_crossing)
    stats_panel.addWidget(mw.label_inside)
    stats_panel.addWidget(mw.label_span_time)
    stats_panel.addWidget(mw.label_span_count)
    stats_panel.addStretch()

    stats_widget = QWidget()
    stats_widget.setLayout(stats_panel)
    stats_widget.setFixedWidth(200)

    bottom_layout.addWidget(stats_widget)
    bottom_layout.addSpacerItem(QSpacerItem(8, 0, QSizePolicy.Fixed, QSizePolicy.Minimum))

    # 曲线图容器
    curve_container = QHBoxLayout()
    curve_container.setContentsMargins(0, 0, 0, 0)

    mw.figure = Figure(figsize=(7, 1.8), dpi=100)
    bg_color = mw.palette().color(QPalette.Window).name()
    mw.figure.patch.set_facecolor(bg_color)
    mw.canvas = FigureCanvas(mw.figure)
    mw.canvas.setStyleSheet(f"background-color: {bg_color}; border: none;")
    curve_container.addWidget(mw.canvas, stretch=1)

    bottom_layout.addLayout(curve_container, stretch=1)
    right_graph_margin = 70
    curve_container.addSpacerItem(QSpacerItem(right_graph_margin, 0, QSizePolicy.Fixed, QSizePolicy.Minimum))
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

def create_param_row(label_text, editor):
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    label = QLabel(label_text)
    label.setFixedWidth(110)
    row.addWidget(label)
    row.addWidget(editor)
    row.addStretch()
    return row


def create_concentric_icon(size=20, color=QColor(0, 0, 0)):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 2)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    # 外圆
    outer_r = size / 2 - 2
    painter.drawEllipse(QPoint(size//2, size//2), outer_r, outer_r)
    # 内圆
    inner_r = outer_r // 2
    painter.drawEllipse(QPoint(size//2, size//2), inner_r, inner_r)

    painter.end()
    return QIcon(pixmap)
