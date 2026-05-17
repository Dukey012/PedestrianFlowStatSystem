from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import pyqtSignal, Qt, QPoint
from PyQt6.QtGui import QPainter, QPen, QColor


class VideoLabel(QLabel):
    region_changed = pyqtSignal(list)
    DEFAULT_REGION_MARGIN = 0.02
    MIN_REGION_SPAN = 0.03

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("border: none; background-color: #f0f0f0;")
        margin = self.DEFAULT_REGION_MARGIN
        self.region = [
            (margin, margin),
            (1.0 - margin, margin),
            (1.0 - margin, 1.0 - margin),
            (margin, 1.0 - margin),
        ]
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
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_region_visible(self, visible):
        self._region_visible = visible
        self.update()

    def reset_region(self):
        self.user_defined_region = False
        self.video_display_rect = None
        margin = self.DEFAULT_REGION_MARGIN
        self.region = [
            (margin, margin),
            (1.0 - margin, margin),
            (1.0 - margin, 1.0 - margin),
            (margin, 1.0 - margin),
        ]
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
        if not self.user_defined_region:
            self.region = self._get_default_region()
            frame_coords = self._map_to_frame_coords()
            self.region_changed.emit(frame_coords)

    def _get_default_region(self):
        margin = self.DEFAULT_REGION_MARGIN
        return [
            self._frame_to_label_norm(margin, margin),
            self._frame_to_label_norm(1.0 - margin, margin),
            self._frame_to_label_norm(1.0 - margin, 1.0 - margin),
            self._frame_to_label_norm(margin, 1.0 - margin),
        ]

    def _frame_to_label_norm(self, frame_x, frame_y):
        if self.video_display_rect is None:
            return (self._clamp01(frame_x), self._clamp01(frame_y))
        vx, vy, vw, vh = self.video_display_rect
        label_w = max(1, self.width())
        label_h = max(1, self.height())
        px = vx + self._clamp01(frame_x) * vw
        py = vy + self._clamp01(frame_y) * vh
        return (px / label_w, py / label_h)

    def _label_norm_to_frame(self, x_norm, y_norm):
        if self.video_display_rect is None:
            return (self._clamp01(x_norm), self._clamp01(y_norm))
        vx, vy, vw, vh = self.video_display_rect
        label_w = max(1, self.width())
        label_h = max(1, self.height())
        px = x_norm * label_w
        py = y_norm * label_h
        frame_x = (px - vx) / vw if vw > 0 else 0.0
        frame_y = (py - vy) / vh if vh > 0 else 0.0
        return (self._clamp01(frame_x), self._clamp01(frame_y))

    def _map_to_frame_coords(self):
        mapped = []
        for (x_norm, y_norm) in self.region:
            frame_x, frame_y = self._label_norm_to_frame(x_norm, y_norm)
            mapped.extend([frame_x, frame_y])
        return mapped

    def _clamp_point_to_video_rect(self, x, y):
        if self.video_display_rect is None:
            return (
                min(max(x, 0.0), float(self.width())),
                min(max(y, 0.0), float(self.height())),
            )
        vx, vy, vw, vh = self.video_display_rect
        return (
            min(max(x, vx), vx + vw),
            min(max(y, vy), vy + vh),
        )

    def _clamp_dragged_point_to_valid_quad(self, point_idx, target_point):
        previous_point = self.region[point_idx]
        candidate = self.region[:]
        candidate[point_idx] = target_point
        if self._is_valid_quad(candidate):
            return target_point

        best_point = previous_point
        low = 0.0
        high = 1.0
        for _ in range(12):
            mid = (low + high) / 2
            interpolated = (
                previous_point[0] + (target_point[0] - previous_point[0]) * mid,
                previous_point[1] + (target_point[1] - previous_point[1]) * mid,
            )
            candidate[point_idx] = interpolated
            if self._is_valid_quad(candidate):
                best_point = interpolated
                low = mid
            else:
                high = mid
        return best_point

    def _is_valid_quad(self, points):
        frame_points = [self._label_norm_to_frame(x, y) for x, y in points]
        xs = [point[0] for point in frame_points]
        ys = [point[1] for point in frame_points]
        if max(xs) - min(xs) < self.MIN_REGION_SPAN:
            return False
        if max(ys) - min(ys) < self.MIN_REGION_SPAN:
            return False

        cross_products = []
        for idx in range(4):
            p1 = frame_points[idx]
            p2 = frame_points[(idx + 1) % 4]
            p3 = frame_points[(idx + 2) % 4]
            cross = (
                (p2[0] - p1[0]) * (p3[1] - p2[1])
                - (p2[1] - p1[1]) * (p3[0] - p2[0])
            )
            if abs(cross) < 1e-6:
                return False
            cross_products.append(cross)

        all_positive = all(value > 0 for value in cross_products)
        all_negative = all(value < 0 for value in cross_products)
        return all_positive or all_negative

    @staticmethod
    def _clamp01(value):
        return min(max(value, 0.0), 1.0)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.underMouse():
            pen = QPen(QColor(100, 100, 100), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            w = self.width()
            h = self.height()
            painter.drawRect(1, 1, w - 3, h - 3)

        if self.pixmap_displayed is None:
            return
        if not self._region_visible:
            return

        pen = QPen(QColor(0, 120, 255), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
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
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            w = self.width()
            h = self.height()
            for i, p in enumerate(self.region):
                px = p[0] * w
                py = p[1] * h
                if (pos.x() - px) ** 2 + (pos.y() - py) ** 2 <= (self.point_radius + 3) ** 2:
                    self.dragging_idx = i
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    break
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._region_enabled:
            return
        if self.dragging_idx >= 0:
            clamped_x, clamped_y = self._clamp_point_to_video_rect(
                event.position().x(),
                event.position().y(),
            )
            new_point = (
                clamped_x / max(1, self.width()),
                clamped_y / max(1, self.height()),
            )
            self.region[self.dragging_idx] = self._clamp_dragged_point_to_valid_quad(
                self.dragging_idx,
                new_point,
            )
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
            self.setCursor(Qt.CursorShape.OpenHandCursor if hovering else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._region_enabled:
            return
        if self.dragging_idx >= 0:
            self.user_defined_region = True
            self.dragging_idx = -1
            self.setCursor(Qt.CursorShape.ArrowCursor)
            frame_coords = self._map_to_frame_coords()
            self.region_changed.emit(frame_coords)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)
