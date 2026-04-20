from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ExportPanel(QWidget):
    choose_output_folder = Signal()
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.output_size_combo = QComboBox(self)
        self.output_folder_edit = QLineEdit(self)
        self.output_folder_edit.setReadOnly(True)
        self.output_folder_button = QPushButton("Browse", self)
        self.captions_location_combo = QComboBox(self)
        self.captions_location_combo.addItem("Same folder as video", userData="same_folder")
        self.captions_location_combo.addItem("captions subfolder", userData="captions")
        self.export_button = QPushButton("Export Selected", self)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log = QTextEdit(self)
        self.log.setReadOnly(True)

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.output_folder_edit)
        folder_layout.addWidget(self.output_folder_button)

        form = QFormLayout()
        form.addRow("Output size:", self.output_size_combo)
        form.addRow("Output folder:", folder_layout)
        form.addRow("Captions location:", self.captions_location_combo)
        form.addRow(QLabel("Progress:"), self.progress)

        group = QGroupBox("Export", self)
        group.setLayout(form)

        layout = QVBoxLayout(self)
        layout.addWidget(group)
        layout.addWidget(self.export_button)
        layout.addWidget(QLabel("Export Log", self))
        layout.addWidget(self.log)

        self.output_folder_button.clicked.connect(self.choose_output_folder)
        self.export_button.clicked.connect(self.export_requested)

    def append_log(self, text: str) -> None:
        self.log.append(text)

