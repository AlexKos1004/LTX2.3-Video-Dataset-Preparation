from __future__ import annotations

import math
from pathlib import Path
import subprocess
import tempfile

from PySide6.QtCore import QByteArray, QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.clip_rules import normalize_8n_plus_1
from app.core.blip2_manager import BLIP2Manager
from app.core.export_pipeline import ExportPipeline, ExportRequest
from app.core.ffmpeg_locator import build_subprocess_env, resolve_binary
from app.core.label_service import LabelService
from app.core.resolution_catalog import filter_available_for_source
from app.core.settings_service import SettingsService, UserSettings
from app.core.video_probe import VideoMetadata, probe_video
from app.core.wd14_manager import WD14Manager
from app.data.project_schema import ClipDefinition, CropRect, VideoProject, load_project, save_project
from app.ui.export_dialog import ExportDialog
from app.ui.preview_player import PreviewPlayer
from app.ui.timeline_widget import TimelineClip, TimelineWidget


class _TaskWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn()
            self.finished.emit(result)
        except Exception as exc:  # pragma: no cover - UI guard
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LTX2.3 Video Dataset Editor")
        self.resize(1500, 920)
        self.setAcceptDrops(True)

        self.settings_service = SettingsService()
        self.user_settings = self.settings_service.load()
        self.export_pipeline = ExportPipeline()
        self.wd14_manager = WD14Manager()
        self.blip2_manager = BLIP2Manager()
        self.label_service = LabelService(self.wd14_manager, self.blip2_manager)

        self.project = VideoProject()
        self.metadata: VideoMetadata | None = None
        self.current_working_width = 0
        self.current_working_height = 0
        self.output_folder_path = self.user_settings.output_folder
        self.captions_mode = self.user_settings.captions_mode

        self.setStatusBar(QStatusBar(self))
        self._build_workspace()
        self._build_crop_dock()
        self._build_caption_dock()
        self._build_logs_dock()
        self._build_menu()
        self._apply_settings_to_ui()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        open_action = QAction("Open Video", self)
        open_action.triggered.connect(self.open_video_dialog)
        export_action = QAction("Export", self)
        export_action.triggered.connect(self.open_export_dialog)
        save_project_action = QAction("Save Project", self)
        save_project_action.triggered.connect(self.save_project_dialog)
        load_project_action = QAction("Load Project", self)
        load_project_action.triggered.connect(self.load_project_dialog)
        file_menu.addAction(open_action)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        file_menu.addAction(save_project_action)
        file_menu.addAction(load_project_action)

        view_menu = self.menuBar().addMenu("View")
        self.preview_view_action = QAction("Preview", self)
        self.preview_view_action.setCheckable(True)
        self.preview_view_action.triggered.connect(self._set_preview_panel_visible)
        self.timeline_view_action = QAction("Timeline", self)
        self.timeline_view_action.setCheckable(True)
        self.timeline_view_action.triggered.connect(self._set_timeline_panel_visible)
        crop_action = self.crop_dock.toggleViewAction()
        crop_action.setText("Crop")
        caption_action = self.caption_dock.toggleViewAction()
        caption_action.setText("Caption")
        logs_action = self.logs_dock.toggleViewAction()
        logs_action.setText("Logs")
        view_menu.addAction(self.preview_view_action)
        view_menu.addAction(self.timeline_view_action)
        view_menu.addAction(crop_action)
        view_menu.addAction(caption_action)
        view_menu.addAction(logs_action)

        settings_menu = self.menuBar().addMenu("Settings")
        redownload_models_action = QAction("Redownload tagger models", self)
        redownload_models_action.triggered.connect(self._redownload_tagger_models)
        settings_menu.addAction(redownload_models_action)

    def _build_workspace(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        self.preview_player = PreviewPlayer(central)
        self.timeline_widget = TimelineWidget(central)
        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical, central)
        self.workspace_splitter.addWidget(self.preview_player)
        self.workspace_splitter.addWidget(self.timeline_widget)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.workspace_splitter)
        self.setCentralWidget(central)

        self.preview_player.crop_changed.connect(self._on_preview_crop_changed)
        self.preview_player.pause_requested_at_seconds.connect(self._on_preview_paused)
        self.preview_player.video_file_dropped.connect(self._load_dropped_video)
        self.timeline_widget.add_clip_requested.connect(self._add_clip_from_playhead)
        self.timeline_widget.auto_clip_requested.connect(self._auto_clip_from_duration)
        self.timeline_widget.remove_clip_requested.connect(self._remove_clip)

    def _build_crop_dock(self) -> None:
        self.crop_dock = QDockWidget("Crop", self)
        self.crop_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        content = QWidget(self.crop_dock)
        form = QFormLayout(content)

        self.output_size_combo = QComboBox(content)
        self.output_size_combo.currentIndexChanged.connect(self._on_output_size_changed)

        self.resize_percent_spin = QSpinBox(content)
        self.resize_percent_spin.setRange(25, 100)
        self.resize_percent_spin.setValue(100)
        self.resize_percent_spin.setSuffix("%")
        self.resize_percent_spin.valueChanged.connect(self._on_resize_percent_changed)
        self.resize_info_label = QLabel("Resize: 100% (source size)", content)

        self.crop_x = QSpinBox(content)
        self.crop_y = QSpinBox(content)
        self.crop_w = QSpinBox(content)
        self.crop_h = QSpinBox(content)
        for spin in [self.crop_x, self.crop_y, self.crop_w, self.crop_h]:
            spin.setMaximum(99999)
            spin.setReadOnly(True)
            spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)

        self.validation_label = QLabel("Validation: open a video to start", content)

        form.addRow("Output size:", self.output_size_combo)
        form.addRow("Resize before crop:", self.resize_percent_spin)
        form.addRow("Resize info:", self.resize_info_label)
        form.addRow("Crop X:", self.crop_x)
        form.addRow("Crop Y:", self.crop_y)
        form.addRow("Crop Width:", self.crop_w)
        form.addRow("Crop Height:", self.crop_h)
        form.addRow("State:", self.validation_label)

        self.crop_dock.setWidget(content)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.crop_dock)

    def _build_caption_dock(self) -> None:
        self.caption_dock = QDockWidget("Caption", self)
        self.caption_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        content = QWidget(self.caption_dock)
        layout = QVBoxLayout(content)

        self.manual_keywords_edit = QLineEdit(content)
        self.manual_keywords_edit.setPlaceholderText("keyword1, keyword2, keyword3")
        self.caption_prefix_edit = QLineEdit(content)
        self.caption_prefix_edit.setPlaceholderText("Global prefix, e.g. my_object")
        self.tagger_combo = QComboBox(content)
        self.tagger_combo.addItem("WD14 Tags", userData="wd14")
        self.tagger_combo.addItem("BLIP2 Caption", userData="blip2")

        self.generate_tags_button = QPushButton("Generate captions for all clips", content)
        self.generate_selected_button = QPushButton("Generate caption for selected clip", content)
        self.apply_prefix_button = QPushButton("Apply prefix to existing captions", content)

        self.labels_table = QTableWidget(0, 2, content)
        self.labels_table.setHorizontalHeaderLabels(["Clip", "Caption"])
        self.labels_table.horizontalHeader().setStretchLastSection(True)
        self.labels_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.labels_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout.addWidget(QLabel("Caption keywords (comma separated):", content))
        layout.addWidget(self.manual_keywords_edit)
        layout.addWidget(QLabel("Tagger:", content))
        layout.addWidget(self.tagger_combo)
        layout.addWidget(QLabel("Caption prefix (added before all tags):", content))
        layout.addWidget(self.caption_prefix_edit)
        layout.addWidget(self.generate_tags_button)
        layout.addWidget(self.generate_selected_button)
        layout.addWidget(self.apply_prefix_button)
        layout.addWidget(QLabel("Per-clip captions:", content))
        layout.addWidget(self.labels_table)

        self.generate_tags_button.clicked.connect(self._generate_tags_for_all_clips)
        self.generate_selected_button.clicked.connect(self._generate_tags_for_selected_clip)
        self.apply_prefix_button.clicked.connect(self._apply_prefix_to_all_captions)

        self.caption_dock.setWidget(content)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.caption_dock)
        self.tabifyDockWidget(self.crop_dock, self.caption_dock)

    def _build_logs_dock(self) -> None:
        self.logs_dock = QDockWidget("Logs", self)
        self.logs_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.logs_text = QTextEdit(self.logs_dock)
        self.logs_text.setReadOnly(True)
        self.logs_dock.setWidget(self.logs_text)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.logs_dock)

    def _apply_settings_to_ui(self) -> None:
        self.caption_prefix_edit.setText("")
        for idx in range(self.tagger_combo.count()):
            if self.tagger_combo.itemData(idx) == self.user_settings.last_tagger:
                self.tagger_combo.setCurrentIndex(idx)
                break
        self.preview_player.set_volume_percent(self.user_settings.volume_percent)
        self._restore_window_layout()

    def _restore_window_layout(self) -> None:
        geometry_b64 = self.user_settings.window_geometry_b64.strip()
        if geometry_b64:
            data = QByteArray.fromBase64(geometry_b64.encode("ascii"))
            if not data.isEmpty():
                self.restoreGeometry(data)

        state_b64 = self.user_settings.window_state_b64.strip()
        if state_b64:
            data = QByteArray.fromBase64(state_b64.encode("ascii"))
            if not data.isEmpty():
                self.restoreState(data)

        self.crop_dock.setVisible(self.user_settings.crop_dock_visible)
        self.caption_dock.setVisible(self.user_settings.caption_dock_visible)
        self.logs_dock.setVisible(self.user_settings.logs_dock_visible)
        self._set_preview_panel_visible(self.user_settings.preview_dock_visible)
        self._set_timeline_panel_visible(self.user_settings.timeline_dock_visible)
        splitter_state_b64 = self.user_settings.workspace_splitter_state_b64.strip()
        if splitter_state_b64:
            state = QByteArray.fromBase64(splitter_state_b64.encode("ascii"))
            if not state.isEmpty():
                self.workspace_splitter.restoreState(state)

        if self.user_settings.main_window_maximized:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _set_preview_panel_visible(self, visible: bool) -> None:
        self.preview_player.setVisible(visible)
        if hasattr(self, "preview_view_action"):
            self.preview_view_action.blockSignals(True)
            self.preview_view_action.setChecked(visible)
            self.preview_view_action.blockSignals(False)

    def _set_timeline_panel_visible(self, visible: bool) -> None:
        self.timeline_widget.setVisible(visible)
        if hasattr(self, "timeline_view_action"):
            self.timeline_view_action.blockSignals(True)
            self.timeline_view_action.setChecked(visible)
            self.timeline_view_action.blockSignals(False)

    def open_video_dialog(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open video",
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi)",
        )
        if not file_path:
            return
        try:
            self.load_video(file_path)
        except Exception as exc:  # pragma: no cover - UI guard
            QMessageBox.critical(self, "Open video failed", str(exc))

    def open_export_dialog(self) -> None:
        dialog = ExportDialog(
            output_folder=self.output_folder_path,
            captions_mode=self.captions_mode,
            parent=self,
        )
        dialog.choose_output_folder.connect(
            lambda: self._choose_output_folder_for_dialog(dialog)
        )
        dialog.export_requested.connect(lambda: self._run_export_from_dialog(dialog))
        dialog.exec()

    @staticmethod
    def _is_supported_video_file(path: str) -> bool:
        suffix = Path(path).suffix.lower()
        return suffix in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

    def _load_dropped_video(self, path: str) -> None:
        if not self._is_supported_video_file(path):
            QMessageBox.warning(self, "Unsupported file", f"Not a supported video: {path}")
            return
        try:
            self.load_video(path)
        except Exception as exc:  # pragma: no cover - UI guard
            QMessageBox.critical(self, "Open video failed", str(exc))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and any(
            url.isLocalFile() and self._is_supported_video_file(url.toLocalFile())
            for url in urls
        ):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        for url in urls:
            if url.isLocalFile():
                local_path = url.toLocalFile()
                if self._is_supported_video_file(local_path):
                    self._load_dropped_video(local_path)
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

    def load_video(self, path: str) -> None:
        self.metadata = probe_video(path)
        self.project = VideoProject(
            source_video_path=path,
            output_folder=self.output_folder_path,
            captions_mode=self.captions_mode,
        )
        self.preview_player.load_video(path)
        self.preview_player.set_source_video_size(self.metadata.width, self.metadata.height)
        poster_frame = self._extract_frame_at_seconds(0.0, "ltx23_poster_frame.jpg")
        if poster_frame:
            self.preview_player.show_poster_frame(poster_frame)
        self._populate_resolution_options()
        self.resize_percent_spin.setValue(100)
        self._on_output_size_changed(self.output_size_combo.currentIndex())
        self._refresh_clip_table()
        self.statusBar().showMessage(f"Loaded video: {path}", 5000)
        self._validate_state()

    def _populate_resolution_options(self) -> None:
        if not self.metadata:
            return
        self.output_size_combo.clear()
        model = self.output_size_combo.model()
        for width, height, allowed in filter_available_for_source(
            self.metadata.width,
            self.metadata.height,
        ):
            label = f"{width}x{height}"
            if width == 960 and height == 544:
                label += " (Base)"
            self.output_size_combo.addItem(label, userData=(width, height))
            row = self.output_size_combo.count() - 1
            item = model.item(row)
            if item is not None:
                item.setEnabled(allowed)
        if self.user_settings.last_resolution:
            idx = self.output_size_combo.findText(self.user_settings.last_resolution)
            if idx >= 0:
                self.output_size_combo.setCurrentIndex(idx)

        if self.output_size_combo.count() > 0:
            selected = self.output_size_combo.currentIndex()
            selected_item = (
                self.output_size_combo.model().item(selected)
                if selected >= 0
                else None
            )
            if selected < 0 or selected_item is None or not selected_item.isEnabled():
                for idx in range(self.output_size_combo.count()):
                    model_item = self.output_size_combo.model().item(idx)
                    if model_item is not None and model_item.isEnabled():
                        self.output_size_combo.setCurrentIndex(idx)
                        break

    def _on_output_size_changed(self, _index: int) -> None:
        if not self.metadata:
            return
        size_data = self.output_size_combo.currentData()
        if not size_data:
            return
        crop_w, crop_h = size_data
        self._sync_resize_and_crop(crop_w, crop_h, recenter=False)
        self._sync_crop_from_preview()
        self._validate_state()

    def _on_resize_percent_changed(self, _value: int) -> None:
        if not self.metadata:
            return
        size_data = self.output_size_combo.currentData()
        if not size_data:
            return
        crop_w, crop_h = size_data
        self._sync_resize_and_crop(crop_w, crop_h, recenter=False)
        self._sync_crop_from_preview()
        self._validate_state()

    def _sync_resize_and_crop(self, crop_w: int, crop_h: int, recenter: bool) -> None:
        if not self.metadata:
            return
        min_ratio = max(crop_w / self.metadata.width, crop_h / self.metadata.height)
        min_percent = max(1, math.ceil(min_ratio * 100))
        selected_percent = self.resize_percent_spin.value()
        effective_percent = max(selected_percent, min_percent)
        if effective_percent > 100:
            effective_percent = 100
        if effective_percent != selected_percent:
            self.resize_percent_spin.blockSignals(True)
            self.resize_percent_spin.setValue(effective_percent)
            self.resize_percent_spin.blockSignals(False)

        working_w = max(32, (int(self.metadata.width * effective_percent / 100) // 32) * 32)
        working_h = max(32, (int(self.metadata.height * effective_percent / 100) // 32) * 32)
        working_w = max(crop_w, min(self.metadata.width, working_w))
        working_h = max(crop_h, min(self.metadata.height, working_h))
        self.current_working_width = working_w
        self.current_working_height = working_h
        self.resize_info_label.setText(
            f"{effective_percent}% -> {working_w}x{working_h} before crop"
        )

        self.preview_player.set_source_video_size(working_w, working_h)
        self.preview_player.set_crop_size(crop_w, crop_h)
        if recenter:
            self.preview_player.set_crop_position(
                max(0, (working_w - crop_w) // 2),
                max(0, (working_h - crop_h) // 2),
            )

    def _on_preview_crop_changed(self, x: int, y: int, w: int, h: int) -> None:
        self.crop_x.setValue(x)
        self.crop_y.setValue(y)
        self.crop_w.setValue(w)
        self.crop_h.setValue(h)
        self._validate_state()

    def _sync_crop_from_preview(self) -> None:
        x, y, w, h = self.preview_player.current_crop_rect()
        self.crop_x.setValue(x)
        self.crop_y.setValue(y)
        self.crop_w.setValue(w)
        self.crop_h.setValue(h)

    def _add_clip_from_playhead(self, duration_seconds: int) -> None:
        if not self.metadata or not self.project.source_video_path:
            QMessageBox.information(self, "No video", "Open a video before adding clips.")
            return
        self._add_clip_at_position(
            start_seconds=self.preview_player.current_position_seconds(),
            duration_seconds=duration_seconds,
            allow_trim_at_end=True,
        )

    def _auto_clip_from_duration(self, duration_seconds: int) -> None:
        if not self.metadata or not self.project.source_video_path:
            QMessageBox.information(self, "No video", "Open a video before auto clip.")
            return
        requested = float(duration_seconds)
        total = float(self.metadata.duration_seconds)
        if requested > total:
            QMessageBox.warning(
                self,
                "Video too short",
                "Selected clip duration exceeds total video duration.",
            )
            return

        start = 0.0
        added = 0
        epsilon = 1e-6
        while start + requested <= total + epsilon:
            created = self._add_clip_at_position(
                start_seconds=start,
                duration_seconds=duration_seconds,
                allow_trim_at_end=False,
            )
            if not created:
                break
            added += 1
            start += requested

        if start < total - epsilon:
            self._append_log(
                "Auto clip: last segment exceeds video duration and was skipped."
            )
        if added > 0:
            self._append_log(f"Auto clip: created {added} clips with duration {duration_seconds}s.")
            self.statusBar().showMessage(
                f"Auto clip created {added} clips",
                4000,
            )

    def _add_clip_at_position(
        self,
        start_seconds: float,
        duration_seconds: int | float,
        allow_trim_at_end: bool,
    ) -> bool:
        if not self.metadata or not self.project.source_video_path:
            return False
        max_duration = max(0.0, self.metadata.duration_seconds - start_seconds)
        requested = float(duration_seconds)
        if max_duration <= 0:
            return False
        if allow_trim_at_end:
            requested = min(requested, max_duration)
        elif requested > max_duration:
            return False
        frame_count = int(round(requested * self.metadata.fps))
        if frame_count <= 0:
            return False
        valid_frame_count = normalize_8n_plus_1(frame_count, mode="floor")
        valid_duration = valid_frame_count / max(self.metadata.fps, 1e-9)

        size_data = self.output_size_combo.currentData()
        if not size_data:
            QMessageBox.warning(self, "Size unavailable", "Choose a valid output size.")
            return False
        target_w, target_h = size_data
        crop_x, crop_y, crop_w, crop_h = self.preview_player.current_crop_rect()
        clip_index = len(self.project.clips) + 1
        clip_name = f"{Path(self.project.source_video_path).stem}_{clip_index:03d}"
        clip = ClipDefinition(
            clip_name=clip_name,
            start_seconds=start_seconds,
            duration_seconds=valid_duration,
            target_width=target_w,
            target_height=target_h,
            crop=CropRect(
                x=crop_x,
                y=crop_y,
                width=crop_w,
                height=crop_h,
            ),
            tags_line="",
            resize_percent=self.resize_percent_spin.value(),
            resize_width=self.current_working_width,
            resize_height=self.current_working_height,
        )
        self.project.clips.append(clip)
        self._refresh_clip_table()
        self._generate_tag_for_clip(len(self.project.clips) - 1)
        self._refresh_labels_table()
        self._validate_state()
        return True

    def _remove_clip(self, index: int) -> None:
        if 0 <= index < len(self.project.clips):
            self.project.clips.pop(index)
            self._refresh_clip_table()
            self._refresh_labels_table()
            self._validate_state()

    def _refresh_clip_table(self) -> None:
        self.timeline_widget.set_clips(
            [
                TimelineClip(
                    clip_name=clip.clip_name,
                    start_seconds=clip.start_seconds,
                    duration_seconds=clip.duration_seconds,
                )
                for clip in self.project.clips
            ]
        )
        self._refresh_labels_table()

    def _refresh_labels_table(self) -> None:
        if not hasattr(self, "labels_table"):
            return
        self.labels_table.setRowCount(len(self.project.clips))
        for row, clip in enumerate(self.project.clips):
            self.labels_table.setItem(row, 0, QTableWidgetItem(clip.clip_name))
            self.labels_table.setItem(row, 1, QTableWidgetItem(clip.tags_line))

    def _choose_output_folder_for_dialog(self, dialog: ExportDialog) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_folder_path)
        if folder:
            dialog.output_folder_edit.setText(folder)

    def _build_export_jobs(self) -> list[ExportRequest]:
        if not self.metadata:
            return []
        output_folder = self.output_folder_path
        captions_mode = self.captions_mode
        if any(not clip.tags_line.strip() for clip in self.project.clips):
            if not self._ensure_selected_tagger_ready():
                raise RuntimeError("Tagger model is not ready for caption generation.")
        jobs = []
        for idx, clip in enumerate(self.project.clips):
            if not clip.tags_line.strip():
                self._generate_tag_for_clip(idx)
            jobs.append(
                ExportRequest(
                    source_video_path=self.project.source_video_path,
                    output_folder=output_folder,
                    clip_name=clip.clip_name,
                    start_seconds=clip.start_seconds,
                    duration_seconds=clip.duration_seconds,
                    fps=self.metadata.fps,
                    crop_x=clip.crop.x,
                    crop_y=clip.crop.y,
                    crop_w=clip.crop.width,
                    crop_h=clip.crop.height,
                    target_width=clip.target_width,
                    target_height=clip.target_height,
                    resize_width=clip.resize_width,
                    resize_height=clip.resize_height,
                    tags_line=clip.tags_line.strip(),
                    captions_mode=captions_mode,
                )
            )
        return jobs

    def _run_export_from_dialog(self, dialog: ExportDialog) -> None:
        if not self.project.clips:
            QMessageBox.information(self, "No clips", "Add at least one clip before export.")
            return
        output_folder = dialog.output_folder_edit.text().strip()
        if not output_folder:
            QMessageBox.warning(self, "Output folder required", "Choose output folder.")
            return
        self.output_folder_path = output_folder
        self.captions_mode = dialog.captions_location_combo.currentData()

        jobs = self._build_export_jobs()
        self.logs_text.clear()
        dialog.progress.setValue(0)
        try:
            def progress_callback(index: int, total: int, path: str) -> None:
                percent = int(index * 100 / max(total, 1))
                dialog.progress.setValue(percent)
                self._append_log(f"[{index}/{total}] Exported {path}")
                QApplication.processEvents()

            results = self.export_pipeline.export_many(jobs, on_progress=progress_callback)
        except Exception as exc:  # pragma: no cover - UI guard
            QMessageBox.critical(self, "Export failed", str(exc))
            return

        for result in results:
            self._append_log(
                f"Saved video: {result.video_path}\nSaved caption: {result.caption_path}"
            )
        self._save_ui_settings()
        QMessageBox.information(self, "Done", f"Exported {len(results)} clips.")
        dialog.accept()

    def _generate_tags_for_all_clips(self) -> None:
        if not self.project.clips:
            QMessageBox.information(self, "No clips", "Add clips before caption generation.")
            return
        if not self._ensure_selected_tagger_ready():
            return
        for idx in range(len(self.project.clips)):
            self._generate_tag_for_clip(idx)
        self._refresh_labels_table()
        self.statusBar().showMessage("Generated captions for all clips", 4000)

    def _generate_tags_for_selected_clip(self) -> None:
        if not self.project.clips:
            QMessageBox.information(self, "No clips", "Add clips before caption generation.")
            return
        if not self._ensure_selected_tagger_ready():
            return
        row = self.labels_table.currentRow() if hasattr(self, "labels_table") else -1
        if row < 0:
            QMessageBox.information(self, "No selection", "Select a clip in WD14 Caption table.")
            return
        self._generate_tag_for_clip(row)
        self._refresh_labels_table()
        self.statusBar().showMessage("Generated caption for selected clip", 3000)

    def _apply_prefix_to_all_captions(self) -> None:
        for clip in self.project.clips:
            clip.tags_line = self._with_caption_prefix(clip.tags_line)
        self._refresh_labels_table()
        self.statusBar().showMessage("Prefix applied to all existing captions", 3000)

    def _generate_tag_for_clip(self, clip_index: int) -> None:
        if clip_index < 0 or clip_index >= len(self.project.clips):
            return
        clip = self.project.clips[clip_index]
        center_sec = clip.start_seconds + (clip.duration_seconds / 2.0)
        frame_path = self._extract_frame_at_seconds(center_sec, f"ltx23_clip_{clip_index}.jpg")
        if frame_path is None:
            # Fallback: use prefix + manual keywords without WD14 frame analysis.
            clip.tags_line = self._with_caption_prefix(self.manual_keywords_edit.text())
            return
        result = self.label_service.generate(
            preview_frame_path=frame_path,
            manual_keywords_line=self.manual_keywords_edit.text(),
            tagger=self.tagger_combo.currentData(),
        )
        clip.tags_line = self._with_caption_prefix(result.final_line)

    def _ensure_selected_tagger_ready(self) -> bool:
        tagger = self.tagger_combo.currentData()
        if tagger == "wd14":
            if self.wd14_manager.is_installed():
                return True
            ok, _ = self._run_blocking_task_with_message(
                "Downloading WD14 model. Please wait...",
                self.wd14_manager.ensure_installed,
            )
            return ok
        if tagger == "blip2":
            if self.blip2_manager.is_initialized():
                return True
            ok, _ = self._run_blocking_task_with_message(
                "Preparing BLIP2 model. This may take a while...",
                self.blip2_manager.ensure_installed,
            )
            return ok
        return True

    def _run_blocking_task_with_message(self, message: str, fn):
        dialog = QProgressDialog(message, "", 0, 0, self)
        dialog.setCancelButton(None)
        dialog.setWindowTitle("Please wait")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.show()

        thread = QThread(self)
        worker = _TaskWorker(fn)
        worker.moveToThread(thread)

        state = {"ok": False, "result": None, "error": ""}

        def on_finished(result) -> None:
            state["ok"] = True
            state["result"] = result
            dialog.close()
            thread.quit()

        def on_failed(error: str) -> None:
            state["ok"] = False
            state["error"] = error
            dialog.close()
            thread.quit()

        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        thread.started.connect(worker.run)
        thread.start()

        while thread.isRunning():
            QApplication.processEvents()

        thread.wait()
        worker.deleteLater()
        thread.deleteLater()
        if not state["ok"]:
            QMessageBox.critical(self, "Operation failed", state["error"] or "Unknown error")
        return state["ok"], state["result"]

    def _redownload_tagger_models(self) -> None:
        answer = QMessageBox.question(
            self,
            "Redownload models",
            "This will re-download WD14 and BLIP2 models. Continue?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def task():
            self.wd14_manager.redownload()
            self.blip2_manager.redownload()
            return True

        ok, _ = self._run_blocking_task_with_message(
            "Re-downloading tagger models. Please wait...",
            task,
        )
        if ok:
            QMessageBox.information(self, "Done", "Tagger models were re-downloaded.")

    def _with_caption_prefix(self, base_line: str) -> str:
        prefix = self.caption_prefix_edit.text().strip().strip(",")
        base = base_line.strip().strip(",")
        if not prefix:
            return base
        if not base:
            return prefix
        if base.lower().startswith(f"{prefix.lower()},"):
            return base
        return f"{prefix}, {base}"

    def _extract_frame_at_seconds(self, seconds: float, filename: str) -> str | None:
        if not self.project.source_video_path:
            return None
        temp_file = Path(tempfile.gettempdir()) / filename
        command = [
            resolve_binary("ffmpeg"),
            "-y",
            "-ss",
            f"{seconds:.3f}",
            "-i",
            self.project.source_video_path,
            "-frames:v",
            "1",
            str(temp_file),
        ]
        try:
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                env=build_subprocess_env(),
            )
        except Exception:
            return None
        return str(temp_file)

    def _on_preview_paused(self, seconds: float) -> None:
        # Rebuild poster on pause so crop overlay is visible again.
        poster_frame = self._extract_frame_at_seconds(seconds, "ltx23_pause_frame.jpg")
        if poster_frame:
            self.preview_player.show_poster_frame(poster_frame)

    def _validate_state(self) -> None:
        if not self.metadata:
            self.validation_label.setText("Validation: open a video to start")
            return
        issues = []
        if self.crop_w.value() % 32 != 0 or self.crop_h.value() % 32 != 0:
            issues.append("crop width/height must be multiple of 32")
        if not self.project.clips:
            issues.append("add at least one clip")
        if issues:
            self.validation_label.setText("Validation: " + "; ".join(issues))
            return
        self.validation_label.setText("Validation: all constraints satisfied")

    def save_project_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "", "JSON (*.json)")
        if not path:
            return
        self._sync_project_from_ui()
        save_project(self.project, path)
        self.statusBar().showMessage(f"Project saved: {path}", 5000)

    def load_project_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load project", "", "JSON (*.json)")
        if not path:
            return
        self.project = load_project(path)
        if self.project.source_video_path:
            self.load_video(self.project.source_video_path)
            self.project = load_project(path)
            self._refresh_clip_table()
            self._refresh_labels_table()
            self._apply_project_state_to_ui()
        self.output_folder_path = self.project.output_folder
        self.captions_mode = self.project.captions_mode
        self.statusBar().showMessage(f"Project loaded: {path}", 5000)

    def _sync_project_from_ui(self) -> None:
        crop_x, crop_y, crop_w, crop_h = self.preview_player.current_crop_rect()
        self.project.output_folder = self.output_folder_path
        self.project.captions_mode = self.captions_mode
        self.project.selected_resolution = self.output_size_combo.currentText()
        self.project.selected_tagger = self.tagger_combo.currentData() or "wd14"
        self.project.caption_prefix = self.caption_prefix_edit.text().strip()
        self.project.manual_keywords_line = self.manual_keywords_edit.text().strip()
        self.project.current_resize_percent = self.resize_percent_spin.value()
        self.project.current_crop = CropRect(
            x=crop_x,
            y=crop_y,
            width=crop_w,
            height=crop_h,
        )
        self.project.keywords = [
            token.strip()
            for token in self.project.manual_keywords_line.split(",")
            if token.strip()
        ]

    def _apply_project_state_to_ui(self) -> None:
        self.caption_prefix_edit.setText(self.project.caption_prefix)
        self.manual_keywords_edit.setText(self.project.manual_keywords_line)
        for idx in range(self.tagger_combo.count()):
            if self.tagger_combo.itemData(idx) == self.project.selected_tagger:
                self.tagger_combo.setCurrentIndex(idx)
                break
        if self.project.selected_resolution:
            idx = self.output_size_combo.findText(self.project.selected_resolution)
            if idx >= 0:
                self.output_size_combo.setCurrentIndex(idx)
        self.resize_percent_spin.setValue(
            min(max(self.project.current_resize_percent, self.resize_percent_spin.minimum()), self.resize_percent_spin.maximum())
        )
        crop = self.project.current_crop
        if crop.width > 0 and crop.height > 0:
            self.preview_player.set_crop_position(crop.x, crop.y)
            self._sync_crop_from_preview()

    def _save_ui_settings(self) -> None:
        geometry_b64 = bytes(self.saveGeometry().toBase64()).decode("ascii")
        state_b64 = bytes(self.saveState().toBase64()).decode("ascii")
        splitter_state_b64 = bytes(self.workspace_splitter.saveState().toBase64()).decode("ascii")
        self.user_settings = UserSettings(
            output_folder=self.output_folder_path,
            captions_mode=self.captions_mode,
            last_resolution=self.output_size_combo.currentText(),
            last_tagger=self.tagger_combo.currentData(),
            window_geometry_b64=geometry_b64,
            window_state_b64=state_b64,
            main_window_maximized=self.isMaximized(),
            crop_dock_visible=self.crop_dock.isVisible(),
            caption_dock_visible=self.caption_dock.isVisible(),
            logs_dock_visible=self.logs_dock.isVisible(),
            preview_dock_visible=self.preview_player.isVisible(),
            timeline_dock_visible=self.timeline_widget.isVisible(),
            workspace_splitter_state_b64=splitter_state_b64,
            volume_percent=self.preview_player.volume_percent(),
        )
        self.settings_service.save(self.user_settings)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_ui_settings()
        super().closeEvent(event)

    def _append_log(self, text: str) -> None:
        self.logs_text.append(text)

