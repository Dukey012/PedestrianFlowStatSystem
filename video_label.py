from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Signal, Qt, QPoint
from PySide6.QtGui import QPainter, QPen, QColor


class VideoLabel(QLabel):
    region_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("border: none; background-color: #f0f0f0;")
        self.region = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.user_defined_region = False
        self.dragging_idx = -1
        self.point_radius = 6
        self.pixmap_displayed = None
        self.video_display_rect = None
        self._region_enabled = True
        self._region_visible = True 

    def set_region_enabled(self, enabled):
        self._region_enabled = enabled
        if not enabled:
            self.dragging_idx = -1
            self.setCursor(Qt.ArrowCursor)

    def set_region_visible(self, visible):
        self._region_visible = visible
        self.update()

    def reset_region(self):
        self.user_defined_region = False
        self.video_display_rect = None
        self.region = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        if self.pixmap_displayed and not self.pixmap_displayed.isNull():
            self.update_video_rect()
        self.update()

    def setPixmap(self, pixmap):
        self.pixmap_displayed = pixmap
        super().setPixmap(pixmap)
        if pixmap and not pixmap.isNull():
            self.update_video_rect()
        self.update()

    def update_video_rect(self):
        if self.pixmap_displayed is None or self.pixmap_displayed.isNull():
            return
        if self.user_defined_region:
            return
        label_w = self.width()
        label_h = self.height()
        pix_w = self.pixmap_displayed.width()
        pix_h = self.pixmap_displayed.height()
        if pix_w == 0 or pix_h == 0:
            return
        ratio = min(label_w / pix_w, label_h / pix_h)
        disp_w = pix_w * ratio
        disp_h = pix_h * ratio
        x = (label_w - disp_w) / 2
        y = (label_h - disp_h) / 2
        self.video_display_rect = (x, y, disp_w, disp_h)
        self.region = [
            (x / label_w, y / label_h),
            ((x + disp_w) / label_w, y / label_h),
            ((x + disp_w) / label_w, (y + disp_h) / label_h),
            (x / label_w, (y + disp_h) / label_h)
        ]
        frame_coords = self._map_to_frame_coords()
        self.region_changed.emit(frame_coords)

    def _map_to_frame_coords(self):
        if self.video_display_rect is None:
            return [c for p in self.region for c in p]
        vx, vy, vw, vh = self.video_display_rect
        label_w = self.width()
        label_h = self.height()
        mapped = []
        for (x_norm, y_norm) in self.region:
            px = x_norm * label_w
            py = y_norm * label_h
            frame_x = (px - vx) / vw if vw > 0 else 0
            frame_y = (py - vy) / vh if vh > 0 else 0
            mapped.extend([frame_x, frame_y])
        return mapped

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.underMouse():
            pen = QPen(QColor(100, 100, 100), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            w = self.width()
            h = self.height()
            painter.drawRect(1, 1, w - 3, h - 3)

        if self.pixmap_displayed is None:
            return
        if not self._region_visible:
            return

        pen = QPen(QColor(0, 120, 255), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        w = self.width()
        h = self.height()
        pts = [QPoint(int(p[0] * w), int(p[1] * h)) for p in self.region]
        painter.drawPolygon(pts)
        painter.setBrush(QColor(255, 255, 0))
        for pt in pts:
            painter.drawEllipse(pt, self.point_radius, self.point_radius)

    def mousePressEvent(self, event):
        if not self._region_enabled:
            return
        if event.button() == Qt.LeftButton:
            pos = event.position()
            w = self.width()
            h = self.height()
            for i, p in enumerate(self.region):
                px = p[0] * w
                py = p[1] * h
                if (pos.x() - px) ** 2 + (pos.y() - py) ** 2 <= (self.point_radius + 3) ** 2:
                    self.dragging_idx = i
                    self.setCursor(Qt.ClosedHandCursor)
                    break
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._region_enabled:
            return
        if self.dragging_idx >= 0:
            new_x = max(0.0, min(1.0, event.position().x() / self.width()))
            new_y = max(0.0, min(1.0, event.position().y() / self.height()))
            self.region[self.dragging_idx] = (new_x, new_y)
            self.update()
            frame_coords = self._map_to_frame_coords()
            self.region_changed.emit(frame_coords)
        else:
            hovering = False
            w = self.width()
            h = self.height()
            for p in self.region:
                px = p[0] * w
                py = p[1] * h
                if (event.position().x() - px) ** 2 + (event.position().y() - py) ** 2 <= (self.point_radius + 3) ** 2:
                    hovering = True
                    break
            self.setCursor(Qt.OpenHandCursor if hovering else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._region_enabled:
            return
        if self.dragging_idx >= 0:
            self.user_defined_region = True
            self.dragging_idx = -1
            self.setCursor(Qt.ArrowCursor)
            frame_coords = self._map_to_frame_coords()
            self.region_changed.emit(frame_coords)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)