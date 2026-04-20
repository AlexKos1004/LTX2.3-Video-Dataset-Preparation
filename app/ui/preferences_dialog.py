from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


HOTKEY_LABELS = {
    "open_video": "Open video",
    "save_project": "Save project",
    "open_project": "Open project",
    "export": "Export",
    "toggle_preview": "Toggle Preview",
    "toggle_timeline": "Toggle Timeline",
    "toggle_crop": "Toggle Crop window",
    "toggle_caption": "Toggle Caption window",
    "toggle_logs": "Toggle Logs window",
    "seek_backward_5s": "Seek -5 seconds",
    "seek_forward_5s": "Seek +5 seconds",
}


class PreferencesDialog(QDialog):
    def __init__(
        self,
        current_hotkeys: dict[str, str],
        default_hotkeys: dict[str, str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resize(520, 420)
        self._default_hotkeys = dict(default_hotkeys)
        self._edits: dict[str, QKeySequenceEdit] = {}

        tabs = QTabWidget(self)
        tabs.addTab(self._build_hotkeys_tab(current_hotkeys), "Hotkeys")

        self.ok_button = QPushButton("OK", self)
        self.cancel_button = QPushButton("Cancel", self)
        self.reset_button = QPushButton("Reset to defaults", self)

        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(buttons)

        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.reset_button.clicked.connect(self._reset_to_defaults)

    def _build_hotkeys_tab(self, current_hotkeys: dict[str, str]) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)
        for key, label in HOTKEY_LABELS.items():
            edit = QKeySequenceEdit(tab)
            edit.setKeySequence(QKeySequence(current_hotkeys.get(key, "")))
            self._edits[key] = edit
            form.addRow(f"{label}:", edit)
        tab.setLayout(form)
        return tab

    def _reset_to_defaults(self) -> None:
        for key, edit in self._edits.items():
            edit.setKeySequence(QKeySequence(self._default_hotkeys.get(key, "")))

    def hotkeys(self) -> dict[str, str]:
        return {key: edit.keySequence().toString() for key, edit in self._edits.items()}

