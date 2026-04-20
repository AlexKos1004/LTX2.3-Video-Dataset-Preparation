from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt


class CropOverlay(QWidget):
    crop_changed = Signal(int, int, int, int)
    video_file_dropped = Signal(str)
    preview_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_width = 0
        self._source_height = 0
        self._crop_x = 0
        self._crop_y = 0
        self._crop_w = 0
        self._crop_h = 0
        self._dragging = False
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._left_pressed = False
        self._press_pos = None
        self._moved_since_press = False
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

    def set_source_size(self, width: int, height: int) -> None:
        self._source_width = max(0, int(width))
        self._source_height = max(0, int(height))
        self._clamp_crop()
        self.update()

    def set_crop_size(self, width: int, height: int) -> None:
        self._crop_w = max(0, int(width))
        self._crop_h = max(0, int(height))
        self._clamp_crop()
        self.crop_changed.emit(self._crop_x, self._crop_y, self._crop_w, self._crop_h)
        self.update()

    def set_crop_position(self, x: int, y: int) -> None:
        self._crop_x = int(x)
        self._crop_y = int(y)
        self._clamp_crop()
        self.crop_changed.emit(self._crop_x, self._crop_y, self._crop_w, self._crop_h)
        self.update()

    def current_crop_rect(self) -> tuple[int, int, int, int]:
        return self._crop_x, self._crop_y, self._crop_w, self._crop_h

    def _clamp_crop(self) -> None:
        if self._source_width <= 0 or self._source_height <= 0:
            return
        self._crop_w = min(self._crop_w, self._source_width)
        self._crop_h = min(self._crop_h, self._source_height)
        self._crop_x = max(0, min(self._crop_x, self._source_width - self._crop_w))
        self._crop_y = max(0, min(self._crop_y, self._source_height - self._crop_h))

    def _video_display_rect(self) -> QRectF:
        if self._source_width <= 0 or self._source_height <= 0:
            return QRectF(0, 0, float(self.width()), float(self.height()))
        if self.width() <= 0 or self.height() <= 0:
            return QRectF()
        scale = min(self.width() / self._source_width, self.height() / self._source_height)
        display_w = self._source_width * scale
        display_h = self._source_height * scale
        x = (self.width() - display_w) / 2.0
        y = (self.height() - display_h) / 2.0
        return QRectF(x, y, display_w, display_h)

    def _source_to_overlay_rect(self) -> QRectF:
        display_rect = self._video_display_rect()
        if display_rect.isNull() or self._source_width <= 0 or self._source_height <= 0:
            return QRectF()
        scale_x = display_rect.width() / self._source_width
        scale_y = display_rect.height() / self._source_height
        return QRectF(
            display_rect.x() + self._crop_x * scale_x,
            display_rect.y() + self._crop_y * scale_y,
            self._crop_w * scale_x,
            self._crop_h * scale_y,
        )

    def _overlay_point_to_source(self, x: float, y: float) -> tuple[int, int]:
        display_rect = self._video_display_rect()
        if display_rect.isNull() or self._source_width <= 0 or self._source_height <= 0:
            return 0, 0
        clamped_x = min(max(x, display_rect.left()), display_rect.right())
        clamped_y = min(max(y, display_rect.top()), display_rect.bottom())
        norm_x = (clamped_x - display_rect.left()) / max(display_rect.width(), 1e-6)
        norm_y = (clamped_y - display_rect.top()) / max(display_rect.height(), 1e-6)
        src_x = int(round(norm_x * self._source_width))
        src_y = int(round(norm_y * self._source_height))
        src_x = min(max(src_x, 0), self._source_width)
        src_y = min(max(src_y, 0), self._source_height)
        return src_x, src_y

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._left_pressed = True
        self._press_pos = event.position()
        self._moved_since_press = False
        crop_rect = self._source_to_overlay_rect()
        if crop_rect.contains(event.position()):
            src_x, src_y = self._overlay_point_to_source(event.position().x(), event.position().y())
            self._dragging = True
            self._drag_offset_x = src_x - self._crop_x
            self._drag_offset_y = src_y - self._crop_y
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._left_pressed and self._press_pos is not None:
            delta = event.position() - self._press_pos
            if abs(delta.x()) > 3 or abs(delta.y()) > 3:
                self._moved_since_press = True
        if self._dragging:
            src_x, src_y = self._overlay_point_to_source(event.position().x(), event.position().y())
            self._crop_x = src_x - self._drag_offset_x
            self._crop_y = src_y - self._drag_offset_y
            self._clamp_crop()
            self.crop_changed.emit(self._crop_x, self._crop_y, self._crop_w, self._crop_h)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._left_pressed
            and not self._moved_since_press
        ):
            self.preview_clicked.emit()
        self._left_pressed = False
        self._press_pos = None
        self._moved_since_press = False
        self._dragging = False
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        for url in urls:
            if url.isLocalFile():
                self.video_file_dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if (
            self._source_width <= 0
            or self._source_height <= 0
            or self._crop_w <= 0
            or self._crop_h <= 0
        ):
            return
        crop_rect = self._source_to_overlay_rect()
        if crop_rect.isNull():
            return
        display_rect = self._video_display_rect()
        if (
            abs(crop_rect.width() - display_rect.width()) < 1.0
            and abs(crop_rect.height() - display_rect.height()) < 1.0
        ):
            # When crop equals full frame, keep border visible inside widget bounds.
            crop_rect = crop_rect.adjusted(2, 2, -2, -2)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        path.addRect(QRectF(0, 0, float(self.width()), float(self.height())))
        path.addRect(crop_rect)
        painter.fillPath(path, QColor(0, 0, 0, 100))

        pen = QPen(QColor(0, 255, 140), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(crop_rect)
        self._draw_handles(painter, crop_rect)

    @staticmethod
    def _draw_handles(painter: QPainter, rect: QRectF) -> None:
        handle_size = 8.0
        half = handle_size / 2.0
        points = [
            rect.topLeft(),
            rect.topRight(),
            rect.bottomLeft(),
            rect.bottomRight(),
        ]
        painter.setBrush(QColor(0, 255, 140))
        for point in points:
            painter.drawRect(
                QRectF(point.x() - half, point.y() - half, handle_size, handle_size)
            )


class PreviewPlayer(QWidget):
    position_changed_seconds = Signal(float)
    crop_changed = Signal(int, int, int, int)
    pause_requested_at_seconds = Signal(float)
    video_file_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icons = self._load_icons()
        self._prime_preview_pending = False
        self._poster_original_pixmap: QPixmap | None = None
        self._slider_was_playing_before_seek = False
        self.setAcceptDrops(True)
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.video_widget = QVideoWidget(self)
        self.media_player.setVideoOutput(self.video_widget)
        self.poster_label = QLabel(self)
        self.poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.poster_label.setStyleSheet("background-color: #101010; color: #b0b0b0;")
        self.poster_label.setText("No preview frame")

        self.video_stack_container = QWidget(self)
        self.video_stack = QStackedLayout(self.video_stack_container)
        self.video_stack.addWidget(self.video_widget)
        self.video_stack.addWidget(self.poster_label)
        self.video_stack.setCurrentWidget(self.poster_label)
        self.crop_overlay = CropOverlay(self.video_stack_container)
        self.crop_overlay.crop_changed.connect(self.crop_changed.emit)
        self.crop_overlay.video_file_dropped.connect(self.video_file_dropped.emit)
        self.crop_overlay.preview_clicked.connect(self._toggle_play_pause)
        self.crop_overlay.raise_()

        self.play_pause_button = QPushButton("", self)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.seek_slider.setRange(0, 0)
        self.time_label = QLabel("00:00 / 00:00", self)
        self.mute_button = QPushButton("", self)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self._last_nonzero_volume = 100
        self.audio_output.setVolume(1.0)
        self.space_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.space_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.play_pause_button.setToolTip("Play / Pause")
        self.mute_button.setToolTip("Mute / Unmute")
        self.play_pause_button.setFixedWidth(36)
        self.mute_button.setFixedWidth(36)
        self._refresh_play_pause_icon()
        self._refresh_mute_icon()

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.play_pause_button)
        controls_layout.addWidget(self.seek_slider, 85)
        controls_layout.addWidget(self.time_label)
        controls_layout.addWidget(QLabel("Vol", self))
        controls_layout.addWidget(self.volume_slider, 15)
        controls_layout.addWidget(self.mute_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.video_stack_container)
        layout.addLayout(controls_layout)

        self.play_pause_button.clicked.connect(self._toggle_play_pause)
        self.space_shortcut.activated.connect(self._toggle_play_pause)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.mute_button.clicked.connect(self._toggle_mute)
        self.seek_slider.sliderMoved.connect(self._seek_slider_moved)
        self.seek_slider.valueChanged.connect(self._seek_slider_value_changed)
        self.seek_slider.sliderPressed.connect(self._on_seek_slider_pressed)
        self.seek_slider.sliderReleased.connect(self._on_seek_slider_released)
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)

    def load_video(self, path: str) -> None:
        self._prime_preview_pending = True
        self._show_video_widget()
        self.media_player.setSource(QUrl.fromLocalFile(str(Path(path))))
        self.crop_overlay.raise_()

    def set_position_seconds(self, seconds: float) -> None:
        self.media_player.setPosition(int(seconds * 1000))

    def current_position_seconds(self) -> float:
        return self.media_player.position() / 1000.0

    def set_source_video_size(self, width: int, height: int) -> None:
        self.crop_overlay.set_source_size(width, height)
        self.crop_overlay.raise_()

    def set_crop_size(self, width: int, height: int) -> None:
        self.crop_overlay.set_crop_size(width, height)
        self.crop_overlay.raise_()

    def set_crop_position(self, x: int, y: int) -> None:
        self.crop_overlay.set_crop_position(x, y)
        self.crop_overlay.raise_()

    def current_crop_rect(self) -> tuple[int, int, int, int]:
        return self.crop_overlay.current_crop_rect()

    def _on_position_changed(self, millis: int) -> None:
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(millis)
        self.seek_slider.blockSignals(False)
        if millis > 0:
            self._show_video_widget()
        self._update_time_label()
        self.position_changed_seconds.emit(millis / 1000.0)

    def _on_duration_changed(self, millis: int) -> None:
        self.seek_slider.setMaximum(millis)
        self._update_time_label()

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if not self._prime_preview_pending:
            return
        if status in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            # Avoid play/pause in status callback (can freeze some backends).
            # Seek to first frame asynchronously after media is ready.
            QTimer.singleShot(0, lambda: self.media_player.setPosition(0))
            self._prime_preview_pending = False

    def show_poster_frame(self, image_path: str | Path) -> None:
        pixmap = QPixmap(str(Path(image_path)))
        if pixmap.isNull():
            return
        self._poster_original_pixmap = pixmap
        self._render_poster()
        self.video_stack.setCurrentWidget(self.poster_label)
        self.crop_overlay.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.crop_overlay.setGeometry(self.video_stack_container.rect())
        self.crop_overlay.raise_()
        self._render_poster()

    def _seek_slider_moved(self, position: int) -> None:
        self._show_video_widget()
        self.media_player.setPosition(position)

    def _seek_slider_value_changed(self, position: int) -> None:
        # Handle click-to-seek on slider groove (not only drag movement).
        self._show_video_widget()
        self.media_player.setPosition(position)

    def _on_seek_slider_pressed(self) -> None:
        self._slider_was_playing_before_seek = (
            self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )

    def _on_seek_slider_released(self) -> None:
        # If user scrubbed while paused/stopped, restore poster + crop overlay.
        if not self._slider_was_playing_before_seek:
            self.pause_requested_at_seconds.emit(self.current_position_seconds())
        self._slider_was_playing_before_seek = False

    def _toggle_play_pause(self) -> None:
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.pause_requested_at_seconds.emit(self.current_position_seconds())
            return
        self._show_video_widget()
        self.media_player.play()

    def _render_poster(self) -> None:
        if self._poster_original_pixmap is None or self._poster_original_pixmap.isNull():
            return
        target = self._poster_original_pixmap.scaled(
            self.video_stack_container.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.poster_label.setPixmap(target)

    def _show_video_widget(self) -> None:
        self.video_stack.setCurrentWidget(self.video_widget)
        self.crop_overlay.raise_()

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self._refresh_play_pause_icon()

    def _on_volume_changed(self, value: int) -> None:
        self.audio_output.setVolume(max(0.0, min(1.0, value / 100.0)))
        if value > 0:
            self._last_nonzero_volume = value
        self.audio_output.setMuted(value == 0)
        self._refresh_mute_icon()

    def _toggle_mute(self) -> None:
        current = self.volume_slider.value()
        if current > 0:
            self.volume_slider.setValue(0)
        else:
            restore = self._last_nonzero_volume if self._last_nonzero_volume > 0 else 100
            self.volume_slider.setValue(restore)

    def _refresh_play_pause_icon(self) -> None:
        is_playing = self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        key = "pause" if is_playing else "play"
        icon = self._icons.get(key)
        if icon is not None:
            self.play_pause_button.setIcon(icon)
            self.play_pause_button.setText("")
        else:
            self.play_pause_button.setText("Pause" if is_playing else "Play")

    def _refresh_mute_icon(self) -> None:
        is_muted = self.audio_output.isMuted() or self.volume_slider.value() == 0
        key = "volume_off" if is_muted else "volume_up"
        icon = self._icons.get(key)
        if icon is not None:
            self.mute_button.setIcon(icon)
            self.mute_button.setText("")
        else:
            self.mute_button.setText("Unmute" if is_muted else "Mute")

    def _load_icons(self) -> dict[str, QIcon]:
        root = Path(__file__).resolve().parents[2]
        mapping = {
            "play": root / "graphics" / "player-play.svg",
            "pause": root / "graphics" / "player-pause.svg",
            "volume_up": root / "graphics" / "volume-up.svg",
            "volume_off": root / "graphics" / "volume-off.svg",
        }
        icons: dict[str, QIcon] = {}
        for key, icon_path in mapping.items():
            if icon_path.exists():
                icons[key] = QIcon(str(icon_path))
        return icons

    def volume_percent(self) -> int:
        return int(self.volume_slider.value())

    def set_volume_percent(self, value: int) -> None:
        clamped = max(0, min(100, int(value)))
        self.volume_slider.setValue(clamped)

    def _update_time_label(self) -> None:
        current = self._format_millis(self.media_player.position())
        total = self._format_millis(self.media_player.duration())
        self.time_label.setText(f"{current} / {total}")

    @staticmethod
    def _format_millis(millis: int) -> str:
        total_seconds = max(0, int(millis / 1000))
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        for url in urls:
            if url.isLocalFile():
                self.video_file_dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return
        super().dropEvent(event)

