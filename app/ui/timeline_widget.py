from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)


@dataclass
class TimelineClip:
    clip_name: str
    start_seconds: float
    duration_seconds: float


class TimelineTrack(QWidget):
    seek_requested = Signal(float)
    clip_selected = Signal(int)
    clip_moved = Signal(int, float)
    clip_context_menu_requested = Signal(int, QPoint)
    background_context_menu_requested = Signal(QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._total_seconds = 0.0
        self._clips: list[TimelineClip] = []
        self._selected_index = -1
        self._playhead_seconds = 0.0
        self._seeking = False
        self._dragging_clip_index = -1
        self._dragging_clip_start = 0.0
        self._dragging_clip_offset = 0.0
        self._forced_move_clip_index = -1
        self._loop_clip_index = -1
        self._is_active = False
        self._has_resolution_warning = False
        self._loop_icon = QPixmap()
        self.setMouseTracking(True)
        self.setMinimumHeight(64)

    def set_total_seconds(self, seconds: float) -> None:
        self._total_seconds = max(0.0, float(seconds))
        self.update()

    def set_clips(self, clips: list[TimelineClip]) -> None:
        self._clips = clips
        if self._selected_index >= len(clips):
            self._selected_index = -1
        if self._loop_clip_index >= len(clips):
            self._loop_clip_index = -1
        self.update()

    def set_playhead_seconds(self, seconds: float) -> None:
        self._playhead_seconds = max(0.0, float(seconds))
        self.update()

    def selected_index(self) -> int:
        return self._selected_index

    def clear_selection(self) -> None:
        self._selected_index = -1
        self.update()

    def begin_move_clip(self, index: int) -> None:
        if 0 <= index < len(self._clips):
            self._selected_index = index
            self._forced_move_clip_index = index
            self.update()

    def set_loop_clip_index(self, index: int) -> None:
        self._loop_clip_index = index
        self.update()

    def set_loop_icon(self, icon_path: str) -> None:
        pix = QPixmap(icon_path)
        if not pix.isNull():
            self._loop_icon = pix
        else:
            self._loop_icon = QPixmap()
        self.update()

    def set_active(self, is_active: bool) -> None:
        self._is_active = bool(is_active)
        self.update()

    def set_resolution_warning(self, has_warning: bool) -> None:
        self._has_resolution_warning = bool(has_warning)
        self.update()

    def _track_rect(self) -> QRect:
        return self.rect().adjusted(8, 8, -8, -8)

    def _seconds_to_x(self, seconds: float) -> int:
        track = self._track_rect()
        if self._total_seconds <= 0 or track.width() <= 1:
            return track.left()
        ratio = max(0.0, min(1.0, seconds / self._total_seconds))
        return track.left() + int(ratio * track.width())

    def _x_to_seconds(self, x: int) -> float:
        track = self._track_rect()
        if track.width() <= 1 or self._total_seconds <= 0:
            return 0.0
        ratio = (x - track.left()) / track.width()
        ratio = max(0.0, min(1.0, ratio))
        return ratio * self._total_seconds

    def _clip_rect(self, clip: TimelineClip) -> QRect:
        track = self._track_rect()
        x1 = self._seconds_to_x(clip.start_seconds)
        x2 = self._seconds_to_x(clip.start_seconds + clip.duration_seconds)
        if x2 <= x1:
            x2 = x1 + 2
        return QRect(x1, track.top() + 12, max(2, x2 - x1), max(8, track.height() - 24))

    def _clip_rect_at_start(self, start_seconds: float, duration_seconds: float) -> QRect:
        track = self._track_rect()
        x1 = self._seconds_to_x(start_seconds)
        x2 = self._seconds_to_x(start_seconds + duration_seconds)
        if x2 <= x1:
            x2 = x1 + 2
        return QRect(x1, track.top() + 12, max(2, x2 - x1), max(8, track.height() - 24))

    def _clip_index_at(self, point: QPoint) -> int:
        for idx, clip in enumerate(self._clips):
            if self._clip_rect(clip).contains(point):
                return idx
        return -1

    @staticmethod
    def _fmt(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        m = total // 60
        s = total % 60
        return f"{m:02d}:{s:02d}"

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        point = event.position().toPoint()
        if self._dragging_clip_index >= 0 and self._dragging_clip_index < len(self._clips):
            clip = self._clips[self._dragging_clip_index]
            tentative_start = self._x_to_seconds(point.x()) - self._dragging_clip_offset
            max_start = max(0.0, self._total_seconds - clip.duration_seconds)
            self._dragging_clip_start = max(0.0, min(max_start, tentative_start))
            self.update()
            event.accept()
            return
        if self._seeking:
            self.seek_requested.emit(self._x_to_seconds(point.x()))
            event.accept()
            return

        idx = self._clip_index_at(point)
        if idx >= 0:
            clip = self._clips[idx]
            start = clip.start_seconds
            duration = clip.duration_seconds
            end = start + duration
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"Start: {self._fmt(start)}\n"
                f"Duration: {self._fmt(duration)}\n"
                f"End: {self._fmt(end)}",
                self,
            )
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = event.position().toPoint()
        idx = self._clip_index_at(point)
        if idx >= 0:
            self._selected_index = idx
            self.clip_selected.emit(idx)
            if (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                or self._forced_move_clip_index == idx
            ):
                clip = self._clips[idx]
                self._dragging_clip_index = idx
                self._dragging_clip_start = clip.start_seconds
                self._dragging_clip_offset = self._x_to_seconds(point.x()) - clip.start_seconds
            else:
                # Click on clip should also seek to the clicked time.
                self.seek_requested.emit(self._x_to_seconds(point.x()))
            self.update()
            event.accept()
            return
        self._selected_index = -1
        if self._track_rect().contains(point):
            self._seeking = True
            self.seek_requested.emit(self._x_to_seconds(point.x()))
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._dragging_clip_index >= 0:
            idx = self._dragging_clip_index
            self._dragging_clip_index = -1
            self.clip_moved.emit(idx, self._dragging_clip_start)
            self.update()
        self._forced_move_clip_index = -1
        self._seeking = False
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        point = event.pos()
        idx = self._clip_index_at(point)
        if idx >= 0:
            self.clip_context_menu_requested.emit(idx, event.globalPos())
            event.accept()
            return
        self.background_context_menu_requested.emit(event.globalPos())
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track = self._track_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        if self._has_resolution_warning and self._is_active:
            painter.setBrush(QColor(130, 32, 32))
        elif self._has_resolution_warning:
            painter.setBrush(QColor(96, 30, 30))
        elif self._is_active:
            painter.setBrush(QColor(28, 64, 44))
        else:
            painter.setBrush(QColor(52, 52, 56))
        painter.drawRoundedRect(track, 6, 6)

        for idx, clip in enumerate(self._clips):
            if idx == self._dragging_clip_index:
                rect = self._clip_rect_at_start(self._dragging_clip_start, clip.duration_seconds)
            else:
                rect = self._clip_rect(clip)
            painter.setBrush(QColor(230, 230, 230))
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawRoundedRect(rect, 2, 2)
            if idx == self._loop_clip_index and not self._loop_icon.isNull():
                icon_h = max(10, rect.height() - 4)
                icon_w = icon_h
                icon_rect = QRect(rect.right() - icon_w - 2, rect.top() + 2, icon_w, icon_h)
                painter.drawPixmap(icon_rect, self._loop_icon)
            if idx == self._selected_index:
                painter.setPen(QPen(QColor(0, 255, 140), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 3, 3)

        # Playhead marker
        playhead_x = self._seconds_to_x(self._playhead_seconds)
        painter.setPen(QPen(QColor(255, 80, 80), 2))
        painter.drawLine(playhead_x, track.top(), playhead_x, track.bottom())


class _PreviewThumbLabel(QLabel):
    clicked = Signal()
    context_menu_requested = Signal(QPoint)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.context_menu_requested.emit(event.globalPos())
        event.accept()


@dataclass
class _TimelineRow:
    container: QWidget
    title_label: QLabel
    preview_thumb: _PreviewThumbLabel
    track: TimelineTrack
    track_scroll: QScrollArea


class TimelineWidget(QWidget):
    VIDEO_TITLE_WIDTH = 220
    VIDEO_TITLE_MAX_CHARS = 24

    add_clip_requested = Signal(int, int)
    auto_clip_requested = Signal(int, int)
    remove_clip_requested = Signal(int, int)
    seek_requested = Signal(int, float)
    clip_selected = Signal(int, int)
    clip_moved = Signal(int, int, float)
    clip_context_menu_requested = Signal(int, int, QPoint)
    video_context_menu_requested = Signal(int, QPoint)
    active_video_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._durations: list[float] = []
        self._rows: list[_TimelineRow] = []
        self._active_video_index = -1
        self._zoom_factor = 1.0
        self._min_zoom = 0.5
        self._max_zoom = 8.0
        self._zoom_step = 1.12
        self._syncing_scrollbars = False

        self.duration_combo = QComboBox(self)
        self.duration_combo.addItems(["5", "10", "15"])
        self.add_clip_button = QPushButton("Add clip at playhead", self)
        self.auto_clip_button = QPushButton("Auto clip", self)
        self.remove_clip_button = QPushButton("Remove selected clip", self)
        self._apply_button_icons()

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Clip Duration (sec):", self))
        controls.addWidget(self.duration_combo)
        controls.addWidget(self.add_clip_button)
        controls.addWidget(self.auto_clip_button)
        controls.addWidget(self.remove_clip_button)

        self.rows_container = QWidget(self)
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        self.rows_layout.addStretch(1)
        self.rows_scroll = QScrollArea(self)
        self.rows_scroll.setWidget(self.rows_container)
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.rows_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.rows_scroll)

        self.add_clip_button.clicked.connect(self._emit_add_request)
        self.auto_clip_button.clicked.connect(self._emit_auto_request)
        self.remove_clip_button.clicked.connect(self._emit_remove_request)

    def selected_duration(self) -> int:
        return int(self.duration_combo.currentText())

    def set_videos(self, videos: list[tuple[str, float]]) -> None:
        while self._rows:
            row = self._rows.pop()
            row.container.setParent(None)
            row.container.deleteLater()
        self._durations = [max(0.0, float(duration)) for _name, duration in videos]
        self._active_video_index = -1
        for idx, (name, duration) in enumerate(videos):
            row = self._build_row(idx, name, float(duration))
            self._rows.append(row)
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row.container)
        if self._rows:
            self.set_active_video_index(0)
        self._update_track_width()
        # Re-run after Qt finishes row layout, so new tracks use final viewport width.
        QTimer.singleShot(0, self._update_track_width)

    def set_video_clips(self, video_index: int, clips: list[TimelineClip]) -> None:
        row = self._row_at(video_index)
        if row:
            row.track.set_clips(clips)

    def set_video_preview_image(self, video_index: int, image_path: str) -> None:
        row = self._row_at(video_index)
        if not row:
            return
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            row.preview_thumb.setPixmap(QPixmap())
            row.preview_thumb.setText("No frame")
            return
        scaled = pixmap.scaled(
            row.preview_thumb.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        row.preview_thumb.setText("")
        row.preview_thumb.setPixmap(scaled)

    def set_video_playhead_seconds(self, video_index: int, seconds: float) -> None:
        row = self._row_at(video_index)
        if row:
            row.track.set_playhead_seconds(seconds)

    def begin_move_clip(self, video_index: int, index: int) -> None:
        row = self._row_at(video_index)
        if row:
            row.track.begin_move_clip(index)

    def set_loop_clip_index(self, video_index: int, index: int) -> None:
        row = self._row_at(video_index)
        if row:
            row.track.set_loop_clip_index(index)

    def set_video_resolution_warning(self, video_index: int, has_warning: bool) -> None:
        row = self._row_at(video_index)
        if row:
            row.track.set_resolution_warning(has_warning)

    def set_loop_icon(self, icon_path: str) -> None:
        for row in self._rows:
            row.track.set_loop_icon(icon_path)

    def set_active_video_index(self, index: int) -> None:
        if index < 0 or index >= len(self._rows):
            return
        self._active_video_index = index
        for row_index, row in enumerate(self._rows):
            is_active = row_index == index
            row.title_label.setStyleSheet(
                "color: #00ff8c; font-weight: 600;" if is_active else "color: #d6d6d6;"
            )
            row.track.set_active(is_active)
        self.active_video_changed.emit(index)

    def active_video_index(self) -> int:
        return self._active_video_index

    def selected_clip_index(self, video_index: int) -> int:
        row = self._row_at(video_index)
        if row:
            return row.track.selected_index()
        return -1

    def _emit_add_request(self) -> None:
        if self._active_video_index >= 0:
            self.add_clip_requested.emit(self._active_video_index, self.selected_duration())

    def _emit_auto_request(self) -> None:
        if self._active_video_index >= 0:
            self.auto_clip_requested.emit(self._active_video_index, self.selected_duration())

    def _emit_remove_request(self) -> None:
        row = self._row_at(self._active_video_index)
        if not row:
            return
        selected = row.track.selected_index()
        if selected >= 0:
            self.remove_clip_requested.emit(self._active_video_index, selected)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_track_width()

    def eventFilter(self, watched, event):  # noqa: N802
        watched_items = set()
        for row in self._rows:
            watched_items.add(row.track_scroll.viewport())
            watched_items.add(row.track)
        if event.type() == QEvent.Type.Resize and watched in watched_items:
            self._update_track_width()
            return False
        if event.type() == QEvent.Type.Wheel and watched in watched_items:
            delta = event.angleDelta().y()
            if delta == 0:
                return False
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._zoom_timeline(delta, float(event.position().x()))
            else:
                self._scroll_horizontally(delta)
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _zoom_timeline(self, wheel_delta: int, cursor_x_in_viewport: float) -> None:
        if not self._durations or max(self._durations) <= 0:
            return
        old_zoom = self._zoom_factor
        factor = self._zoom_step if wheel_delta > 0 else (1.0 / self._zoom_step)
        new_zoom = max(self._min_zoom, min(self._max_zoom, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-6:
            return

        row = self._row_at(self._active_video_index if self._active_video_index >= 0 else 0)
        if row is None:
            return
        bar = row.track_scroll.horizontalScrollBar()
        old_content_x = bar.value() + cursor_x_in_viewport
        scale_ratio = new_zoom / old_zoom
        self._zoom_factor = new_zoom
        self._update_track_width()
        new_content_x = old_content_x * scale_ratio
        new_value = int(new_content_x - cursor_x_in_viewport)
        self._sync_horizontal_scroll_to_all(new_value)

    def _scroll_horizontally(self, wheel_delta: int) -> None:
        row = self._row_at(self._active_video_index if self._active_video_index >= 0 else 0)
        if row is None:
            return
        bar = row.track_scroll.horizontalScrollBar()
        if bar.maximum() <= 0:
            return
        step = 64
        new_value = bar.value() - step if wheel_delta > 0 else bar.value() + step
        self._sync_horizontal_scroll_to_all(new_value)

    def _update_track_width(self) -> None:
        for index, row in enumerate(self._rows):
            viewport_width = row.track_scroll.viewport().width()
            if viewport_width <= 0:
                continue
            total = self._durations[index] if index < len(self._durations) else 0.0
            if total <= 0:
                row.track.setFixedWidth(max(260, viewport_width))
                continue
            base_pixels_per_sec = max(8.0, viewport_width / total)
            effective_pixels_per_sec = base_pixels_per_sec * self._zoom_factor
            content_width = int(total * effective_pixels_per_sec) + 16
            row.track.setFixedWidth(max(viewport_width, content_width))

    def _sync_horizontal_scroll_from(self, source_index: int, value: int) -> None:
        if self._syncing_scrollbars:
            return
        self._syncing_scrollbars = True
        try:
            for index, row in enumerate(self._rows):
                if index == source_index:
                    continue
                row.track_scroll.horizontalScrollBar().setValue(value)
        finally:
            self._syncing_scrollbars = False

    def _sync_horizontal_scroll_to_all(self, value: int) -> None:
        self._syncing_scrollbars = True
        try:
            for row in self._rows:
                row.track_scroll.horizontalScrollBar().setValue(value)
        finally:
            self._syncing_scrollbars = False

    def _row_at(self, index: int) -> _TimelineRow | None:
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def _build_row(self, row_index: int, name: str, duration: float) -> _TimelineRow:
        container = QWidget(self.rows_container)
        container.setFixedHeight(64)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title_label = QLabel(self._format_video_title(name), container)
        title_label.setFixedWidth(self.VIDEO_TITLE_WIDTH)
        title_label.setStyleSheet("color: #d6d6d6;")

        preview_thumb = _PreviewThumbLabel(container)
        preview_thumb.setFixedSize(114, 64)
        preview_thumb.setStyleSheet("background-color: #202024; border: 1px solid #303038;")
        preview_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_thumb.setText("No frame")
        preview_thumb.clicked.connect(lambda i=row_index: self.set_active_video_index(i))
        preview_thumb.context_menu_requested.connect(
            lambda global_pos, i=row_index: self.video_context_menu_requested.emit(i, global_pos)
        )

        track = TimelineTrack(container)
        track.setFixedHeight(64)
        track.set_total_seconds(duration)
        track_scroll = QScrollArea(container)
        track_scroll.setWidget(track)
        track_scroll.setWidgetResizable(False)
        track_scroll.setFixedHeight(64)
        track_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        track_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        track_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        track_scroll.viewport().installEventFilter(self)
        track.installEventFilter(self)
        track_scroll.horizontalScrollBar().valueChanged.connect(
            lambda value, i=row_index: self._sync_horizontal_scroll_from(i, value)
        )
        track.seek_requested.connect(lambda seconds, i=row_index: self._on_row_seek(i, seconds))
        track.clip_selected.connect(lambda clip_index, i=row_index: self._on_row_clip_selected(i, clip_index))
        track.clip_moved.connect(lambda clip_index, seconds, i=row_index: self._on_row_clip_moved(i, clip_index, seconds))
        track.clip_context_menu_requested.connect(
            lambda clip_index, global_pos, i=row_index: self._on_row_clip_context_menu(i, clip_index, global_pos)
        )
        track.background_context_menu_requested.connect(
            lambda global_pos, i=row_index: self.video_context_menu_requested.emit(i, global_pos)
        )

        layout.addWidget(title_label)
        layout.addWidget(preview_thumb)
        layout.addWidget(track_scroll, stretch=1)

        return _TimelineRow(
            container=container,
            title_label=title_label,
            preview_thumb=preview_thumb,
            track=track,
            track_scroll=track_scroll,
        )

    def _format_video_title(self, name: str) -> str:
        clean = name.strip()
        if len(clean) <= self.VIDEO_TITLE_MAX_CHARS:
            return clean.ljust(self.VIDEO_TITLE_MAX_CHARS)
        return clean[: self.VIDEO_TITLE_MAX_CHARS - 3] + "..."

    def _apply_button_icons(self) -> None:
        graphics_dir = Path(__file__).resolve().parents[2] / "graphics"
        mapping = [
            (self.add_clip_button, graphics_dir / "cut-add.svg"),
            (self.auto_clip_button, graphics_dir / "cut-auto.svg"),
            (self.remove_clip_button, graphics_dir / "cut-remove.svg"),
        ]
        for button, icon_path in mapping:
            if icon_path.exists():
                button.setIcon(QIcon(str(icon_path)))

    def _on_row_seek(self, video_index: int, seconds: float) -> None:
        self.set_active_video_index(video_index)
        self.seek_requested.emit(video_index, seconds)

    def _on_row_clip_selected(self, video_index: int, clip_index: int) -> None:
        self.set_active_video_index(video_index)
        self.clip_selected.emit(video_index, clip_index)

    def _on_row_clip_moved(self, video_index: int, clip_index: int, seconds: float) -> None:
        self.set_active_video_index(video_index)
        self.clip_moved.emit(video_index, clip_index, seconds)

    def _on_row_clip_context_menu(self, video_index: int, clip_index: int, global_pos: QPoint) -> None:
        self.set_active_video_index(video_index)
        self.clip_context_menu_requested.emit(video_index, clip_index, global_pos)

