from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class ExportDialog(QDialog):
    choose_output_folder = Signal()
    export_requested = Signal()

    def __init__(
        self,
        output_folder: str,
        captions_mode: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.resize(520, 250)

        self.output_folder_edit = QLineEdit(self)
        self.output_folder_edit.setReadOnly(True)
        self.output_folder_edit.setText(output_folder)
        self.output_folder_button = QPushButton("Browse", self)

        self.captions_location_combo = QComboBox(self)
        self.captions_location_combo.addItem("Same folder as video", userData="same_folder")
        self.captions_location_combo.addItem("captions subfolder", userData="captions")
        for idx in range(self.captions_location_combo.count()):
            if self.captions_location_combo.itemData(idx) == captions_mode:
                self.captions_location_combo.setCurrentIndex(idx)
                break

        self.frames_combo = QComboBox(self)
        for fps in (9, 17, 25):
            self.frames_combo.addItem(str(fps), userData=fps)
        self.frames_combo.setCurrentIndex(1)
        self.frames_example_label = QLabel("", self)
        self._update_frames_example_label()

        folder_row = QHBoxLayout()
        folder_row.addWidget(self.output_folder_edit)
        folder_row.addWidget(self.output_folder_button)

        form = QFormLayout()
        form.addRow("Output folder:", folder_row)
        form.addRow("Captions location:", self.captions_location_combo)
        form.addRow("Frames per second (8n+1):", self.frames_combo)
        form.addRow("Example for 5s clip:", self.frames_example_label)

        form_container = QWidget(self)
        form_container.setLayout(form)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        self.export_button = QPushButton("Start Export", self)
        self.cancel_button = QPushButton("Cancel", self)

        button_row = QHBoxLayout()
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.addWidget(form_container)
        layout.addWidget(QLabel("Progress:", self))
        layout.addWidget(self.progress)
        layout.addLayout(button_row)

        self.output_folder_button.clicked.connect(self.choose_output_folder)
        self.export_button.clicked.connect(self.export_requested)
        self.cancel_button.clicked.connect(self.reject)
        self.frames_combo.currentIndexChanged.connect(self._update_frames_example_label)

    def selected_fps(self) -> int:
        value = self.frames_combo.currentData()
        if isinstance(value, int):
            return value
        try:
            return int(self.frames_combo.currentText().strip())
        except Exception:
            return 17

    def _update_frames_example_label(self) -> None:
        fps = self.selected_fps()
        self.frames_example_label.setText(f"{fps * 5} frames (fps x duration)")

