from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass
class TimelineClip:
    clip_name: str
    start_seconds: float
    duration_seconds: float


class TimelineWidget(QWidget):
    add_clip_requested = Signal(int)
    auto_clip_requested = Signal(int)
    remove_clip_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.duration_combo = QComboBox(self)
        self.duration_combo.addItems(["5", "10", "15"])
        self.add_clip_button = QPushButton("Add clip at playhead", self)
        self.auto_clip_button = QPushButton("Auto clip", self)
        self.remove_clip_button = QPushButton("Remove selected clip", self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Clip Duration (sec):", self))
        controls.addWidget(self.duration_combo)
        controls.addWidget(self.add_clip_button)
        controls.addWidget(self.auto_clip_button)
        controls.addWidget(self.remove_clip_button)

        self.clips_table = QTableWidget(0, 3, self)
        self.clips_table.setHorizontalHeaderLabels(["Clip", "Start", "Duration"])
        self.clips_table.horizontalHeader().setStretchLastSection(True)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.clips_table)

        self.add_clip_button.clicked.connect(self._emit_add_request)
        self.auto_clip_button.clicked.connect(self._emit_auto_request)
        self.remove_clip_button.clicked.connect(self._emit_remove_request)

    def selected_duration(self) -> int:
        return int(self.duration_combo.currentText())

    def set_clips(self, clips: list[TimelineClip]) -> None:
        self.clips_table.setRowCount(len(clips))
        for row, clip in enumerate(clips):
            self.clips_table.setItem(row, 0, QTableWidgetItem(clip.clip_name))
            self.clips_table.setItem(row, 1, QTableWidgetItem(f"{clip.start_seconds:.2f}"))
            self.clips_table.setItem(row, 2, QTableWidgetItem(f"{clip.duration_seconds:.2f}"))

    def _emit_add_request(self) -> None:
        self.add_clip_requested.emit(self.selected_duration())

    def _emit_auto_request(self) -> None:
        self.auto_clip_requested.emit(self.selected_duration())

    def _emit_remove_request(self) -> None:
        selected = self.clips_table.currentRow()
        if selected >= 0:
            self.remove_clip_requested.emit(selected)

