from __future__ import annotations

import math
from pathlib import Path
import subprocess
import tempfile
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QObject, QPoint, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
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

from app.core.blip2_manager import BLIP2Manager
from app.core.export_pipeline import ExportPipeline, ExportRequest
from app.core.ffmpeg_locator import build_subprocess_env, resolve_binary
from app.core.label_service import LabelService
from app.core.resolution_catalog import filter_available_for_source
from app.core.settings_service import SettingsService, UserSettings
from app.core.video_probe import VideoMetadata, probe_video
from app.core.wd14_manager import WD14Manager
from app.data.project_schema import ClipDefinition, CropRect, VideoAsset, VideoProject, load_project, save_project
from app.ui.export_dialog import ExportDialog
from app.ui.preferences_dialog import PreferencesDialog
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


@dataclass
class _VideoRuntime:
    asset: VideoAsset
    metadata: VideoMetadata


class MainWindow(QMainWindow):
    DEFAULT_HOTKEYS = {
        "open_video": "Ctrl+O",
        "save_project": "Ctrl+S",
        "open_project": "Ctrl+Alt+O",
        "export": "Ctrl+E",
        "toggle_preview": "Ctrl+Shift+P",
        "toggle_timeline": "Ctrl+Shift+T",
        "toggle_crop": "Ctrl+Shift+R",
        "toggle_caption": "Ctrl+Shift+C",
        "toggle_logs": "Ctrl+Shift+L",
        "seek_backward_5s": "Left",
        "seek_forward_5s": "Right",
    }

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
        self.video_runtimes: list[_VideoRuntime] = []
        self.active_video_index = -1
        self.current_working_width = 0
        self.current_working_height = 0
        self.output_folder_path = self.user_settings.output_folder
        self.captions_mode = self.user_settings.captions_mode
        self.global_selected_resolution = self._resolution_key_from_label(
            self.user_settings.last_resolution or "960x544"
        )
        self.hotkeys = self._normalized_hotkeys(self.user_settings.hotkeys)
        self._pending_timeline_seek_seconds = 0.0
        self._pending_timeline_seek_video_index = -1
        self._timeline_seek_preview_timer = QTimer(self)
        self._timeline_seek_preview_timer.setSingleShot(True)
        self._timeline_seek_preview_timer.timeout.connect(self._refresh_preview_after_timeline_seek)
        self._loop_clip_index = -1
        self._loop_video_index = -1
        self._syncing_active_video = False
        self._applying_video_state = False
        self._resolution_warning_paths: set[str] = set()
        self._loop_track_icon_path = str(Path(__file__).resolve().parents[2] / "graphics" / "loop.svg")
        self._loop_menu_icon_path = str(Path(__file__).resolve().parents[2] / "graphics" / "loop-alt.svg")

        self.setStatusBar(QStatusBar(self))
        self._build_workspace()
        self._build_crop_dock()
        self._build_caption_dock()
        self._build_logs_dock()
        self._build_menu()
        self._apply_settings_to_ui()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self.open_video_action = QAction("Open Video", self)
        self.open_video_action.triggered.connect(self.open_video_dialog)
        self.export_action = QAction("Export", self)
        self.export_action.triggered.connect(self.open_export_dialog)
        self.save_project_action = QAction("Save Project", self)
        self.save_project_action.triggered.connect(self.save_project_dialog)
        self.load_project_action = QAction("Load Project", self)
        self.load_project_action.triggered.connect(self.load_project_dialog)
        file_menu.addAction(self.open_video_action)
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_project_action)
        file_menu.addAction(self.load_project_action)

        view_menu = self.menuBar().addMenu("View")
        self.preview_view_action = QAction("Preview", self)
        self.preview_view_action.setCheckable(True)
        self.preview_view_action.triggered.connect(self._set_preview_panel_visible)
        self.timeline_view_action = QAction("Timeline", self)
        self.timeline_view_action.setCheckable(True)
        self.timeline_view_action.triggered.connect(self._set_timeline_panel_visible)
        self.crop_view_action = self.crop_dock.toggleViewAction()
        self.crop_view_action.setText("Crop")
        self.caption_view_action = self.caption_dock.toggleViewAction()
        self.caption_view_action.setText("Caption")
        self.logs_view_action = self.logs_dock.toggleViewAction()
        self.logs_view_action.setText("Logs")
        view_menu.addAction(self.preview_view_action)
        view_menu.addAction(self.timeline_view_action)
        view_menu.addAction(self.crop_view_action)
        view_menu.addAction(self.caption_view_action)
        view_menu.addAction(self.logs_view_action)

        self.seek_backward_action = QAction("Seek backward 5s", self)
        self.seek_backward_action.triggered.connect(self._seek_active_timeline_backward)
        self.seek_forward_action = QAction("Seek forward 5s", self)
        self.seek_forward_action.triggered.connect(self._seek_active_timeline_forward)
        # Keep as global app actions (not shown in menus).
        self.addAction(self.seek_backward_action)
        self.addAction(self.seek_forward_action)

        settings_menu = self.menuBar().addMenu("Settings")
        preference_menu = settings_menu.addMenu("Preference")
        self.preference_hotkeys_action = QAction("Hotkeys...", self)
        self.preference_hotkeys_action.triggered.connect(self.open_preferences_dialog)
        preference_menu.addAction(self.preference_hotkeys_action)
        settings_menu.addSeparator()
        redownload_models_action = QAction("Redownload tagger models", self)
        redownload_models_action.triggered.connect(self._redownload_tagger_models)
        settings_menu.addAction(redownload_models_action)
        self._apply_hotkeys()

    def _normalized_hotkeys(self, hotkeys: dict[str, str] | None) -> dict[str, str]:
        normalized = dict(self.DEFAULT_HOTKEYS)
        if hotkeys:
            for key, value in hotkeys.items():
                if key in normalized and isinstance(value, str):
                    normalized[key] = value
        return normalized

    def _apply_hotkeys(self) -> None:
        self.open_video_action.setShortcut(self.hotkeys["open_video"])
        self.save_project_action.setShortcut(self.hotkeys["save_project"])
        self.load_project_action.setShortcut(self.hotkeys["open_project"])
        self.export_action.setShortcut(self.hotkeys["export"])
        self.preview_view_action.setShortcut(self.hotkeys["toggle_preview"])
        self.timeline_view_action.setShortcut(self.hotkeys["toggle_timeline"])
        self.crop_view_action.setShortcut(self.hotkeys["toggle_crop"])
        self.caption_view_action.setShortcut(self.hotkeys["toggle_caption"])
        self.logs_view_action.setShortcut(self.hotkeys["toggle_logs"])
        self.seek_backward_action.setShortcut(self.hotkeys["seek_backward_5s"])
        self.seek_forward_action.setShortcut(self.hotkeys["seek_forward_5s"])

    def open_preferences_dialog(self) -> None:
        dialog = PreferencesDialog(
            current_hotkeys=self.hotkeys,
            default_hotkeys=self.DEFAULT_HOTKEYS,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.hotkeys = self._normalized_hotkeys(dialog.hotkeys())
        self._apply_hotkeys()
        self._save_ui_settings()

    def _build_workspace(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        self.preview_player = PreviewPlayer(central)
        self.timeline_widget = TimelineWidget(central)
        self.timeline_widget.set_loop_icon(self._loop_track_icon_path)
        self.preview_player.setMinimumHeight(140)
        self.timeline_widget.setMinimumHeight(140)
        self.timeline_widget.setEnabled(False)
        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical, central)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(self.preview_player)
        self.workspace_splitter.addWidget(self.timeline_widget)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.workspace_splitter)
        self.setCentralWidget(central)

        self.preview_player.crop_changed.connect(self._on_preview_crop_changed)
        self.preview_player.pause_requested_at_seconds.connect(self._on_preview_paused)
        self.preview_player.video_file_dropped.connect(self._load_dropped_video)
        self.preview_player.position_changed_seconds.connect(self._on_preview_playhead_for_timeline)
        self.preview_player.position_changed_seconds.connect(self._on_preview_position_changed)
        self.timeline_widget.add_clip_requested.connect(self._add_clip_from_playhead)
        self.timeline_widget.auto_clip_requested.connect(self._auto_clip_from_duration)
        self.timeline_widget.remove_clip_requested.connect(self._remove_clip)
        self.timeline_widget.seek_requested.connect(self._on_timeline_seek_requested)
        self.timeline_widget.clip_selected.connect(self._on_timeline_clip_selected)
        self.timeline_widget.clip_moved.connect(self._on_timeline_clip_moved)
        self.timeline_widget.clip_context_menu_requested.connect(self._on_timeline_clip_context_menu)
        self.timeline_widget.video_context_menu_requested.connect(self._on_timeline_video_context_menu)
        self.timeline_widget.active_video_changed.connect(self._on_timeline_active_video_changed)

    def _build_crop_dock(self) -> None:
        self.crop_dock = QDockWidget("Crop", self)
        self.crop_dock.setObjectName("cropDock")
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
        self.caption_dock.setObjectName("captionDock")
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

        self.labels_table = QTableWidget(0, 3, content)
        self.labels_table.setHorizontalHeaderLabels(["Video", "Clip", "Caption"])
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
        self.logs_dock.setObjectName("logsDock")
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
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open videos",
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi)",
        )
        if not file_paths:
            return
        for file_path in file_paths:
            if not file_path:
                continue
            candidate = Path(file_path)
            if not candidate.is_file():
                QMessageBox.warning(self, "Open video failed", f"Not a valid file: {file_path}")
                continue
            try:
                self.load_video(file_path)
            except Exception as exc:  # pragma: no cover - UI guard
                QMessageBox.critical(self, "Open video failed", str(exc))
                break

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
        opened_any = False
        for url in urls:
            if url.isLocalFile():
                local_path = url.toLocalFile()
                if self._is_supported_video_file(local_path):
                    self._load_dropped_video(local_path)
                    opened_any = True
        if opened_any:
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def load_video(self, path: str) -> None:
        metadata = probe_video(path)
        asset = VideoAsset(source_video_path=path)
        runtime = _VideoRuntime(asset=asset, metadata=metadata)
        self.video_runtimes.append(runtime)
        self.project.videos.append(asset)
        self._rebuild_timeline_rows()
        self.timeline_widget.setEnabled(True)
        self._set_active_video_index(len(self.video_runtimes) - 1)
        self._update_timeline_resolution_warnings(log_new=True)
        self.statusBar().showMessage(f"Loaded video: {path}", 5000)
        self._refresh_labels_table()
        self._validate_state()

    def _populate_resolution_options(self) -> None:
        metadata = self._current_metadata()
        if not self.video_runtimes or metadata is None:
            return
        is_vertical = metadata.height > metadata.width
        probe_width = metadata.height if is_vertical else metadata.width
        probe_height = metadata.width if is_vertical else metadata.height
        self.output_size_combo.blockSignals(True)
        self.output_size_combo.clear()
        model = self.output_size_combo.model()
        for base_w, base_h, allowed in filter_available_for_source(
            probe_width,
            probe_height,
        ):
            width = base_h if is_vertical else base_w
            height = base_w if is_vertical else base_h
            label = f"{width}x{height}"
            if base_w == 960 and base_h == 544:
                label += " (Base)"
            self.output_size_combo.addItem(label, userData=(width, height))
            row = self.output_size_combo.count() - 1
            item = model.item(row)
            if item is not None:
                item.setEnabled(allowed)
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
        self.output_size_combo.blockSignals(False)

    @staticmethod
    def _resolution_key_from_label(label: str) -> str:
        key = label.split(" ", 1)[0].strip().lower()
        parts = key.split("x", 1)
        if len(parts) != 2:
            return key
        try:
            w = int(parts[0].strip())
            h = int(parts[1].strip())
        except Exception:
            return key
        return f"{max(w, h)}x{min(w, h)}"

    @staticmethod
    def _resolution_dims_from_key(key: str) -> tuple[int, int]:
        normalized = MainWindow._resolution_key_from_label(key)
        parts = normalized.split("x", 1)
        if len(parts) != 2:
            return 960, 544
        try:
            return int(parts[0]), int(parts[1])
        except Exception:
            return 960, 544

    @staticmethod
    def _resolution_for_metadata(base_w: int, base_h: int, metadata: VideoMetadata) -> tuple[int, int]:
        if metadata.height > metadata.width:
            return base_h, base_w
        return base_w, base_h

    def _find_resolution_index(self, selected_resolution: str) -> int:
        if not selected_resolution:
            return -1
        idx = self.output_size_combo.findText(selected_resolution)
        if idx >= 0:
            return idx
        wanted_key = self._resolution_key_from_label(selected_resolution)
        for row in range(self.output_size_combo.count()):
            item_key = self._resolution_key_from_label(self.output_size_combo.itemText(row))
            if item_key == wanted_key:
                return row
        return -1

    def _current_runtime(self) -> _VideoRuntime | None:
        if 0 <= self.active_video_index < len(self.video_runtimes):
            return self.video_runtimes[self.active_video_index]
        return None

    def _current_video(self) -> VideoAsset | None:
        runtime = self._current_runtime()
        return runtime.asset if runtime else None

    def _current_metadata(self) -> VideoMetadata | None:
        runtime = self._current_runtime()
        return runtime.metadata if runtime else None

    def _on_timeline_active_video_changed(self, index: int) -> None:
        if self._syncing_active_video:
            return
        self._set_active_video_index(index, from_timeline=True)

    def _set_active_video_index(self, index: int, from_timeline: bool = False) -> None:
        if index < 0 or index >= len(self.video_runtimes):
            return
        if index == self.active_video_index:
            return
        if self._current_runtime() is not None:
            self._persist_current_video_ui_state()
            if self.preview_player.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.preview_player.media_player.pause()
        self.active_video_index = index
        self._set_loop_clip_index(-1)
        if not from_timeline:
            self._syncing_active_video = True
            try:
                self.timeline_widget.set_active_video_index(index)
            finally:
                self._syncing_active_video = False
        self._apply_active_video_to_ui()

    def _rebuild_timeline_rows(self) -> None:
        videos = [
            (Path(runtime.asset.source_video_path).name, runtime.metadata.duration_seconds)
            for runtime in self.video_runtimes
        ]
        self.timeline_widget.set_videos(videos)
        for idx, runtime in enumerate(self.video_runtimes):
            self.timeline_widget.set_video_clips(
                idx,
                [
                    TimelineClip(
                        clip_name=clip.clip_name,
                        start_seconds=clip.start_seconds,
                        duration_seconds=clip.duration_seconds,
                    )
                    for clip in runtime.asset.clips
                ],
            )
            poster_frame = self._extract_frame_at_seconds(
                0.0,
                f"ltx23_poster_frame_{idx}.jpg",
                source_video_path=runtime.asset.source_video_path,
            )
            if poster_frame:
                self.timeline_widget.set_video_preview_image(idx, poster_frame)
        self._update_timeline_resolution_warnings(log_new=False)

    def _persist_current_video_ui_state(self) -> None:
        runtime = self._current_runtime()
        if not runtime:
            return
        crop_x, crop_y, crop_w, crop_h = self.preview_player.current_crop_rect()
        runtime.asset.current_resize_percent = self.resize_percent_spin.value()
        runtime.asset.current_crop = CropRect(
            x=crop_x,
            y=crop_y,
            width=crop_w,
            height=crop_h,
        )

    def _apply_active_video_to_ui(self) -> None:
        runtime = self._current_runtime()
        if not runtime:
            return
        self._applying_video_state = True
        try:
            self.preview_player.load_video(runtime.asset.source_video_path)
            self.preview_player.set_source_video_size(runtime.metadata.width, runtime.metadata.height)
            self._populate_resolution_options()
            self.output_size_combo.blockSignals(True)
            if self.global_selected_resolution:
                idx = self._find_resolution_index(self.global_selected_resolution)
                if idx >= 0:
                    self.output_size_combo.setCurrentIndex(idx)
            self.output_size_combo.blockSignals(False)

            self.resize_percent_spin.blockSignals(True)
            self.resize_percent_spin.setValue(
                min(
                    max(runtime.asset.current_resize_percent, self.resize_percent_spin.minimum()),
                    self.resize_percent_spin.maximum(),
                )
            )
            self.resize_percent_spin.blockSignals(False)
            self._on_output_size_changed(self.output_size_combo.currentIndex(), log_warnings=False)
            if runtime.asset.current_crop.width > 0 and runtime.asset.current_crop.height > 0:
                # Restore saved per-video position only after crop size is configured.
                self.preview_player.set_crop_position(
                    runtime.asset.current_crop.x,
                    runtime.asset.current_crop.y,
                )
                self._sync_crop_from_preview()
        finally:
            self._applying_video_state = False

        # Persist post-clamp crop so per-video state stays stable after switch/play/pause.
        crop_x, crop_y, crop_w, crop_h = self.preview_player.current_crop_rect()
        runtime.asset.current_crop = CropRect(x=crop_x, y=crop_y, width=crop_w, height=crop_h)

        poster_frame = self._extract_frame_at_seconds(0.0, "ltx23_poster_frame.jpg")
        if poster_frame:
            self.preview_player.show_poster_frame(poster_frame)
            if self.active_video_index >= 0:
                self.timeline_widget.set_video_preview_image(self.active_video_index, poster_frame)
        self._refresh_clip_table()

    def _on_output_size_changed(self, _index: int, log_warnings: bool = True) -> None:
        metadata = self._current_metadata()
        if not metadata:
            return
        size_data = self.output_size_combo.currentData()
        if not size_data:
            return
        self.global_selected_resolution = self._resolution_key_from_label(
            self.output_size_combo.currentText()
        )
        crop_w, crop_h = size_data
        base_w, base_h = self._resolution_dims_from_key(self.global_selected_resolution)
        for runtime in self.video_runtimes:
            video_w, video_h = self._resolution_for_metadata(base_w, base_h, runtime.metadata)
            runtime.asset.current_crop.width = video_w
            runtime.asset.current_crop.height = video_h
        self._sync_resize_and_crop(crop_w, crop_h, recenter=False)
        self._sync_crop_from_preview()
        self._sync_all_video_clips_to_current_settings()
        self._update_timeline_resolution_warnings(log_new=log_warnings)
        self._validate_state()

    def _update_timeline_resolution_warnings(self, log_new: bool) -> None:
        if not self.video_runtimes:
            return
        base_w, base_h = self._resolution_dims_from_key(self.global_selected_resolution)
        current_warning_paths: set[str] = set()
        newly_logged_paths: set[str] = set()
        for index, runtime in enumerate(self.video_runtimes):
            target_w, target_h = self._resolution_for_metadata(base_w, base_h, runtime.metadata)
            is_smaller = runtime.metadata.width < target_w or runtime.metadata.height < target_h
            self.timeline_widget.set_video_resolution_warning(index, is_smaller)
            if is_smaller:
                current_warning_paths.add(runtime.asset.source_video_path)
                if log_new and runtime.asset.source_video_path not in self._resolution_warning_paths:
                    video_name = Path(runtime.asset.source_video_path).name
                    self._append_log(
                        f"Please reduce output size: video '{video_name}' has smaller resolution "
                        f"({runtime.metadata.width}x{runtime.metadata.height}) than selected "
                        f"{target_w}x{target_h}."
                    )
                    newly_logged_paths.add(runtime.asset.source_video_path)
        if log_new:
            # Keep only currently relevant warning paths, then add new logs from this pass.
            self._resolution_warning_paths = (
                self._resolution_warning_paths.intersection(current_warning_paths)
            ).union(newly_logged_paths)

    def _on_resize_percent_changed(self, _value: int) -> None:
        metadata = self._current_metadata()
        if not metadata:
            return
        video = self._current_video()
        if video:
            video.current_resize_percent = self.resize_percent_spin.value()
        size_data = self.output_size_combo.currentData()
        if not size_data:
            return
        crop_w, crop_h = size_data
        self._sync_resize_and_crop(crop_w, crop_h, recenter=False)
        self._sync_crop_from_preview()
        self._sync_all_video_clips_to_current_settings()
        self._validate_state()

    @staticmethod
    def _compute_working_size(
        source_width: int,
        source_height: int,
        crop_w: int,
        crop_h: int,
        selected_percent: int,
    ) -> tuple[int, int, int]:
        min_ratio = max(crop_w / source_width, crop_h / source_height)
        min_percent = max(1, math.ceil(min_ratio * 100))
        effective_percent = max(selected_percent, min_percent)
        if effective_percent > 100:
            effective_percent = 100
        working_w = max(32, (int(source_width * effective_percent / 100) // 32) * 32)
        working_h = max(32, (int(source_height * effective_percent / 100) // 32) * 32)
        working_w = max(crop_w, min(source_width, working_w))
        working_h = max(crop_h, min(source_height, working_h))
        return effective_percent, working_w, working_h

    def _sync_resize_and_crop(self, crop_w: int, crop_h: int, recenter: bool) -> None:
        metadata = self._current_metadata()
        if not metadata:
            return
        selected_percent = self.resize_percent_spin.value()
        effective_percent, working_w, working_h = self._compute_working_size(
            source_width=metadata.width,
            source_height=metadata.height,
            crop_w=crop_w,
            crop_h=crop_h,
            selected_percent=selected_percent,
        )
        if effective_percent != selected_percent:
            self.resize_percent_spin.blockSignals(True)
            self.resize_percent_spin.setValue(effective_percent)
            self.resize_percent_spin.blockSignals(False)
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
        if self._applying_video_state:
            self._validate_state()
            return
        runtime = self._current_runtime()
        if runtime:
            runtime.asset.current_crop = CropRect(x=x, y=y, width=w, height=h)
            selected_index = self.timeline_widget.selected_clip_index(self.active_video_index)
            if 0 <= selected_index < len(runtime.asset.clips):
                clip = runtime.asset.clips[selected_index]
                clip.crop = CropRect(x=x, y=y, width=w, height=h)
                clip.resize_percent = self.resize_percent_spin.value()
                clip.resize_width = self.current_working_width
                clip.resize_height = self.current_working_height
        self._validate_state()

    def _sync_crop_from_preview(self) -> None:
        x, y, w, h = self.preview_player.current_crop_rect()
        self.crop_x.setValue(x)
        self.crop_y.setValue(y)
        self.crop_w.setValue(w)
        self.crop_h.setValue(h)

    def _sync_all_video_clips_to_current_settings(self) -> None:
        active_runtime = self._current_runtime()
        if not active_runtime:
            return
        size_data = self.output_size_combo.currentData()
        if not size_data:
            return
        base_w, base_h = self._resolution_dims_from_key(self.global_selected_resolution)
        selected_percent = int(self.resize_percent_spin.value())

        for runtime in self.video_runtimes:
            target_w, target_h = self._resolution_for_metadata(base_w, base_h, runtime.metadata)
            effective_percent, working_w, working_h = self._compute_working_size(
                source_width=runtime.metadata.width,
                source_height=runtime.metadata.height,
                crop_w=target_w,
                crop_h=target_h,
                selected_percent=selected_percent,
            )
            max_x = max(0, working_w - target_w)
            max_y = max(0, working_h - target_h)
            current_crop_x = max(0, min(int(runtime.asset.current_crop.x), max_x))
            current_crop_y = max(0, min(int(runtime.asset.current_crop.y), max_y))

            runtime.asset.current_resize_percent = effective_percent
            runtime.asset.current_crop = CropRect(
                x=current_crop_x,
                y=current_crop_y,
                width=target_w,
                height=target_h,
            )
            for clip in runtime.asset.clips:
                clip_crop_x = max(0, min(int(clip.crop.x), max_x))
                clip_crop_y = max(0, min(int(clip.crop.y), max_y))
                clip.target_width = int(target_w)
                clip.target_height = int(target_h)
                clip.crop = CropRect(
                    x=clip_crop_x,
                    y=clip_crop_y,
                    width=target_w,
                    height=target_h,
                )
                clip.resize_percent = effective_percent
                clip.resize_width = working_w
                clip.resize_height = working_h

    def _add_clip_from_playhead(self, video_index: int, duration_seconds: int) -> None:
        self._set_active_video_index(video_index)
        if not self._current_metadata() or not self._current_video():
            QMessageBox.information(self, "No video", "Open a video before adding clips.")
            return
        resume_playback = self._pause_playback_for_tagger()
        try:
            self._add_clip_at_position(
                start_seconds=self.preview_player.current_position_seconds(),
                duration_seconds=duration_seconds,
                allow_trim_at_end=True,
            )
        finally:
            self._resume_playback_after_tagger(resume_playback)

    def _auto_clip_from_duration(self, video_index: int, duration_seconds: int) -> None:
        self._set_active_video_index(video_index)
        metadata = self._current_metadata()
        if not metadata or not self._current_video():
            QMessageBox.information(self, "No video", "Open a video before auto clip.")
            return
        resume_playback = self._pause_playback_for_tagger()
        try:
            requested = float(duration_seconds)
            total = float(metadata.duration_seconds)
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
        finally:
            self._resume_playback_after_tagger(resume_playback)

    def _pause_playback_for_tagger(self) -> bool:
        player = self.preview_player.media_player
        was_playing = player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if was_playing:
            player.pause()
        return was_playing

    def _resume_playback_after_tagger(self, should_resume: bool) -> None:
        if should_resume:
            self.preview_player.media_player.play()

    def _add_clip_at_position(
        self,
        start_seconds: float,
        duration_seconds: int | float,
        allow_trim_at_end: bool,
    ) -> bool:
        video = self._current_video()
        metadata = self._current_metadata()
        if not metadata or not video:
            return False
        max_duration = max(0.0, metadata.duration_seconds - start_seconds)
        requested = float(duration_seconds)
        if max_duration <= 0:
            return False
        if allow_trim_at_end:
            requested = min(requested, max_duration)
        elif requested > max_duration:
            return False
        if requested <= 0:
            return False

        size_data = self.output_size_combo.currentData()
        if not size_data:
            QMessageBox.warning(self, "Size unavailable", "Choose a valid output size.")
            return False
        target_w, target_h = size_data
        crop_x, crop_y, crop_w, crop_h = self.preview_player.current_crop_rect()
        clip_index = len(video.clips) + 1
        clip_name = f"{Path(video.source_video_path).stem}_{clip_index:03d}"
        clip = ClipDefinition(
            clip_name=clip_name,
            start_seconds=start_seconds,
            duration_seconds=requested,
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
        video.clips.append(clip)
        self._refresh_clip_table()
        self._generate_tag_for_clip(len(video.clips) - 1)
        self._refresh_labels_table()
        self._validate_state()
        return True

    def _remove_clip(self, video_index: int, index: int) -> None:
        self._set_active_video_index(video_index)
        video = self._current_video()
        if not video:
            return
        if 0 <= index < len(video.clips):
            video.clips.pop(index)
            if self._loop_clip_index == index:
                self._set_loop_clip_index(-1)
            elif self._loop_clip_index > index:
                self._set_loop_clip_index(self._loop_clip_index - 1)
            self._refresh_clip_table()
            self._refresh_labels_table()
            self._validate_state()

    def _on_timeline_clip_selected(self, video_index: int, index: int) -> None:
        self._set_active_video_index(video_index)
        video = self._current_video()
        if video and 0 <= index < len(video.clips):
            clip = video.clips[index]
            self.preview_player.set_crop_position(clip.crop.x, clip.crop.y)
            runtime = self._current_runtime()
            if runtime:
                runtime.asset.current_crop = CropRect(
                    x=clip.crop.x,
                    y=clip.crop.y,
                    width=clip.crop.width,
                    height=clip.crop.height,
                )
            self._sync_crop_from_preview()
            self._on_timeline_seek_requested(video_index, video.clips[index].start_seconds)

    def _on_timeline_clip_moved(self, video_index: int, index: int, new_start_seconds: float) -> None:
        self._set_active_video_index(video_index)
        video = self._current_video()
        if video and 0 <= index < len(video.clips):
            video.clips[index].start_seconds = max(0.0, float(new_start_seconds))
            if self._ensure_selected_tagger_ready():
                self._generate_tag_for_clip(index)
                self._refresh_labels_table()
            self._refresh_clip_table()
            self._on_timeline_seek_requested(video_index, video.clips[index].start_seconds)

    def _on_timeline_clip_context_menu(self, video_index: int, index: int, global_pos: QPoint) -> None:
        self._set_active_video_index(video_index)
        video = self._current_video()
        if not video or not (0 <= index < len(video.clips)):
            return
        menu = QMenu(self)
        delete_action = menu.addAction("Delete")
        loop_action = menu.addAction("Loop")
        loop_action.setCheckable(True)
        loop_action.setChecked(self._loop_clip_index == index)
        if Path(self._loop_menu_icon_path).exists():
            loop_action.setIcon(QIcon(self._loop_menu_icon_path))
        move_action = menu.addAction("Move")
        menu.addSeparator()
        remove_video_action = menu.addAction("Remove video from project")

        chosen = menu.exec(global_pos)
        if chosen == delete_action:
            self._remove_clip(video_index, index)
            return
        if chosen == move_action:
            self.timeline_widget.begin_move_clip(video_index, index)
            return
        if chosen == remove_video_action:
            self._remove_video_from_project(video_index)
            return
        if chosen == loop_action:
            if self._loop_clip_index == index:
                self._set_loop_clip_index(-1)
            else:
                self._set_loop_clip_index(index)
                self._on_timeline_seek_requested(video_index, video.clips[index].start_seconds)

    def _on_timeline_video_context_menu(self, video_index: int, global_pos: QPoint) -> None:
        if not (0 <= video_index < len(self.video_runtimes)):
            return
        self._set_active_video_index(video_index)
        menu = QMenu(self)
        remove_action = menu.addAction("Remove video from project")
        chosen = menu.exec(global_pos)
        if chosen == remove_action:
            self._remove_video_from_project(video_index)

    def _remove_video_from_project(self, video_index: int) -> None:
        if not (0 <= video_index < len(self.video_runtimes)):
            return
        video_name = Path(self.video_runtimes[video_index].asset.source_video_path).name
        answer = QMessageBox.question(
            self,
            "Remove video",
            f"Remove '{video_name}' from project?\nAll its clips and captions will be removed.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.preview_player.media_player.pause()
        removing_active = video_index == self.active_video_index
        self.video_runtimes.pop(video_index)
        if 0 <= video_index < len(self.project.videos):
            self.project.videos.pop(video_index)

        if self._loop_video_index == video_index:
            self._loop_video_index = -1
            self._loop_clip_index = -1
        elif self._loop_video_index > video_index:
            self._loop_video_index -= 1

        self._rebuild_timeline_rows()
        if not self.video_runtimes:
            self.active_video_index = -1
            self.timeline_widget.setEnabled(False)
            self.preview_player.clear()
            self._resolution_warning_paths = set()
            self._set_loop_clip_index(-1)
            self._refresh_labels_table()
            self._validate_state()
            self.statusBar().showMessage(f"Removed video: {video_name}", 4000)
            return

        self.timeline_widget.setEnabled(True)
        if removing_active:
            new_index = min(video_index, len(self.video_runtimes) - 1)
            self._set_active_video_index(new_index)
        elif self.active_video_index > video_index:
            self._set_active_video_index(self.active_video_index - 1)
        else:
            # keep current active video index as-is and refresh clip table/labels
            self._refresh_clip_table()
        self._refresh_labels_table()
        self._validate_state()
        self.statusBar().showMessage(f"Removed video: {video_name}", 4000)

    def _set_loop_clip_index(self, index: int) -> None:
        if 0 <= self._loop_video_index < len(self.video_runtimes):
            self.timeline_widget.set_loop_clip_index(self._loop_video_index, -1)
        self._loop_clip_index = index
        self._loop_video_index = self.active_video_index if index >= 0 else -1
        if self._loop_video_index >= 0:
            self.timeline_widget.set_loop_clip_index(self._loop_video_index, index)

    def _on_preview_position_changed(self, seconds: float) -> None:
        video = self._current_video()
        if (
            not video
            or self._loop_video_index != self.active_video_index
            or not (0 <= self._loop_clip_index < len(video.clips))
        ):
            return
        clip = video.clips[self._loop_clip_index]
        clip_start = clip.start_seconds
        clip_end = clip.start_seconds + clip.duration_seconds
        state = self.preview_player.media_player.playbackState()

        if state == QMediaPlayer.PlaybackState.PlayingState and seconds >= clip_end:
            self.preview_player.set_position_seconds(clip_start)
            return
        if seconds < clip_start or seconds > clip_end:
            # Moving playhead outside clip disables loop mode.
            self._set_loop_clip_index(-1)

    def _on_timeline_seek_requested(self, video_index: int, seconds: float) -> None:
        self._set_active_video_index(video_index)
        self.timeline_widget.set_video_playhead_seconds(video_index, seconds)
        self.preview_player.set_position_seconds(seconds)
        # On some backends frame preview does not refresh while paused
        # until playback starts. Refresh poster asynchronously.
        if self.preview_player.media_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._pending_timeline_seek_seconds = seconds
            self._pending_timeline_seek_video_index = video_index
            self._timeline_seek_preview_timer.start(120)

    def _seek_active_timeline_backward(self) -> None:
        self._seek_active_timeline_relative(-5.0)

    def _seek_active_timeline_forward(self) -> None:
        self._seek_active_timeline_relative(5.0)

    def _seek_active_timeline_relative(self, delta_seconds: float) -> None:
        metadata = self._current_metadata()
        if metadata is None or self.active_video_index < 0:
            return
        current = self.preview_player.current_position_seconds()
        target = max(0.0, min(float(metadata.duration_seconds), current + float(delta_seconds)))
        self._on_timeline_seek_requested(self.active_video_index, target)

    def _on_preview_playhead_for_timeline(self, seconds: float) -> None:
        if self.active_video_index >= 0:
            self.timeline_widget.set_video_playhead_seconds(self.active_video_index, seconds)

    def _refresh_preview_after_timeline_seek(self) -> None:
        seconds = self._pending_timeline_seek_seconds
        video_index = self._pending_timeline_seek_video_index
        runtime = self.video_runtimes[video_index] if 0 <= video_index < len(self.video_runtimes) else None
        frame = self._extract_frame_at_seconds(
            seconds,
            "ltx23_seek_frame.jpg",
            source_video_path=runtime.asset.source_video_path if runtime else None,
        )
        if frame:
            self.preview_player.show_poster_frame(frame)
            if runtime:
                self.timeline_widget.set_video_preview_image(video_index, frame)

    def _refresh_clip_table(self) -> None:
        video = self._current_video()
        clips = video.clips if video else []
        if self.active_video_index >= 0:
            self.timeline_widget.set_video_clips(
                self.active_video_index,
                [
                    TimelineClip(
                        clip_name=clip.clip_name,
                        start_seconds=clip.start_seconds,
                        duration_seconds=clip.duration_seconds,
                    )
                    for clip in clips
                ],
            )
        self._refresh_labels_table()

    def _refresh_labels_table(self) -> None:
        if not hasattr(self, "labels_table"):
            return
        rows: list[tuple[str, ClipDefinition]] = []
        for runtime in self.video_runtimes:
            video_name = Path(runtime.asset.source_video_path).name
            for clip in runtime.asset.clips:
                rows.append((video_name, clip))
        self.labels_table.setRowCount(len(rows))
        for row, (video_name, clip) in enumerate(rows):
            self.labels_table.setItem(row, 0, QTableWidgetItem(video_name))
            self.labels_table.setItem(row, 1, QTableWidgetItem(clip.clip_name))
            self.labels_table.setItem(row, 2, QTableWidgetItem(clip.tags_line))

    def _choose_output_folder_for_dialog(self, dialog: ExportDialog) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_folder_path)
        if folder:
            dialog.output_folder_edit.setText(folder)

    def _build_export_jobs(self, forced_fps: int | None = None) -> list[ExportRequest]:
        self._sync_all_video_clips_to_current_settings()
        output_folder = self.output_folder_path
        captions_mode = self.captions_mode
        all_clips = [clip for runtime in self.video_runtimes for clip in runtime.asset.clips]
        if any(not clip.tags_line.strip() for clip in all_clips):
            if not self._ensure_selected_tagger_ready():
                raise RuntimeError("Tagger model is not ready for caption generation.")
        jobs = []
        for video_index, runtime in enumerate(self.video_runtimes):
            for idx, clip in enumerate(runtime.asset.clips):
                if not clip.tags_line.strip():
                    self._generate_tag_for_clip(idx, video_index=video_index)
                jobs.append(
                    ExportRequest(
                        source_video_path=runtime.asset.source_video_path,
                        output_folder=output_folder,
                        clip_name=clip.clip_name,
                        start_seconds=clip.start_seconds,
                        duration_seconds=clip.duration_seconds,
                        fps=runtime.metadata.fps,
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
                        forced_fps=forced_fps,
                    )
                )
        return jobs

    def _run_export_from_dialog(self, dialog: ExportDialog) -> None:
        if not any(runtime.asset.clips for runtime in self.video_runtimes):
            QMessageBox.information(self, "No clips", "Add at least one clip before export.")
            return
        output_folder = dialog.output_folder_edit.text().strip()
        if not output_folder:
            QMessageBox.warning(self, "Output folder required", "Choose output folder.")
            return
        self.output_folder_path = output_folder
        self.captions_mode = dialog.captions_location_combo.currentData()

        jobs = self._build_export_jobs(forced_fps=dialog.selected_fps())
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
        all_clips = [clip for runtime in self.video_runtimes for clip in runtime.asset.clips]
        if not all_clips:
            QMessageBox.information(self, "No clips", "Add clips before caption generation.")
            return
        if not self._ensure_selected_tagger_ready():
            return
        for video_index, runtime in enumerate(self.video_runtimes):
            for clip_index in range(len(runtime.asset.clips)):
                self._generate_tag_for_clip(clip_index, video_index=video_index)
        self._refresh_labels_table()
        self.statusBar().showMessage("Generated captions for all clips", 4000)

    def _generate_tags_for_selected_clip(self) -> None:
        if not any(runtime.asset.clips for runtime in self.video_runtimes):
            QMessageBox.information(self, "No clips", "Add clips before caption generation.")
            return
        clip_ref = self._clip_ref_from_labels_row(self.labels_table.currentRow() if hasattr(self, "labels_table") else -1)
        if clip_ref is None:
            QMessageBox.information(self, "No selection", "Select a clip in WD14 Caption table.")
            return
        if not self._ensure_selected_tagger_ready():
            return
        video_index, clip_index = clip_ref
        self._generate_tag_for_clip(clip_index, video_index=video_index)
        self._refresh_labels_table()
        self.statusBar().showMessage("Generated caption for selected clip", 3000)

    def _apply_prefix_to_all_captions(self) -> None:
        for runtime in self.video_runtimes:
            for clip in runtime.asset.clips:
                clip.tags_line = self._with_caption_prefix(clip.tags_line)
        self._refresh_labels_table()
        self.statusBar().showMessage("Prefix applied to all existing captions", 3000)

    def _clip_ref_from_labels_row(self, row: int) -> tuple[int, int] | None:
        if row < 0:
            return None
        cursor = 0
        for video_index, runtime in enumerate(self.video_runtimes):
            clip_count = len(runtime.asset.clips)
            if row < cursor + clip_count:
                return video_index, row - cursor
            cursor += clip_count
        return None

    def _generate_tag_for_clip(self, clip_index: int, video_index: int | None = None) -> None:
        if video_index is None:
            video_index = self.active_video_index
        if not (0 <= video_index < len(self.video_runtimes)):
            return
        runtime = self.video_runtimes[video_index]
        if clip_index < 0 or clip_index >= len(runtime.asset.clips):
            return
        clip = runtime.asset.clips[clip_index]
        center_sec = clip.start_seconds + (clip.duration_seconds / 2.0)
        frame_path = self._extract_frame_at_seconds(
            center_sec,
            f"ltx23_clip_{video_index}_{clip_index}.jpg",
            source_video_path=runtime.asset.source_video_path,
        )
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

    def _extract_frame_at_seconds(
        self,
        seconds: float,
        filename: str,
        source_video_path: str | None = None,
    ) -> str | None:
        source_path = source_video_path
        if not source_path:
            video = self._current_video()
            source_path = video.source_video_path if video else ""
        if not source_path:
            return None
        temp_file = Path(tempfile.gettempdir()) / filename
        command = [
            resolve_binary("ffmpeg"),
            "-y",
            "-ss",
            f"{seconds:.3f}",
            "-i",
            source_path,
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
        metadata = self._current_metadata()
        if not metadata:
            self.validation_label.setText("Validation: open a video to start")
            return
        issues = []
        if self.crop_w.value() % 32 != 0 or self.crop_h.value() % 32 != 0:
            issues.append("crop width/height must be multiple of 32")
        video = self._current_video()
        if not video or not video.clips:
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
        project = load_project(path)
        self.project = project
        self.global_selected_resolution = self._resolution_key_from_label(
            self.project.selected_resolution or self.global_selected_resolution
        )
        self.video_runtimes = []
        self._resolution_warning_paths = set()
        self.active_video_index = -1
        for asset in self.project.videos:
            if not asset.source_video_path:
                continue
            try:
                metadata = probe_video(asset.source_video_path)
            except Exception as exc:  # pragma: no cover - UI guard
                self._append_log(f"Skipped video from project: {asset.source_video_path} ({exc})")
                continue
            self.video_runtimes.append(_VideoRuntime(asset=asset, metadata=metadata))
        self._rebuild_timeline_rows()
        if self.video_runtimes:
            self.timeline_widget.setEnabled(True)
            self._set_active_video_index(0)
        else:
            self.timeline_widget.setEnabled(False)
            self.preview_player.clear()
        self._refresh_labels_table()
        self._apply_project_state_to_ui()
        self.output_folder_path = self.project.output_folder
        self.captions_mode = self.project.captions_mode
        self.statusBar().showMessage(f"Project loaded: {path}", 5000)

    def _sync_project_from_ui(self) -> None:
        self._persist_current_video_ui_state()
        self.project.output_folder = self.output_folder_path
        self.project.captions_mode = self.captions_mode
        self.project.selected_resolution = self.global_selected_resolution
        self.project.selected_tagger = self.tagger_combo.currentData() or "wd14"
        self.project.caption_prefix = self.caption_prefix_edit.text().strip()
        self.project.manual_keywords_line = self.manual_keywords_edit.text().strip()
        self.project.videos = [runtime.asset for runtime in self.video_runtimes]
        self.project.keywords = [
            token.strip()
            for token in self.project.manual_keywords_line.split(",")
            if token.strip()
        ]

    def _apply_project_state_to_ui(self) -> None:
        if self.project.selected_resolution:
            self.global_selected_resolution = self.project.selected_resolution
        self.caption_prefix_edit.setText(self.project.caption_prefix)
        self.manual_keywords_edit.setText(self.project.manual_keywords_line)
        for idx in range(self.tagger_combo.count()):
            if self.tagger_combo.itemData(idx) == self.project.selected_tagger:
                self.tagger_combo.setCurrentIndex(idx)
                break
        if self.active_video_index >= 0:
            self._apply_active_video_to_ui()
        self._refresh_labels_table()

    def _save_ui_settings(self) -> None:
        geometry_b64 = bytes(self.saveGeometry().toBase64()).decode("ascii")
        state_b64 = bytes(self.saveState().toBase64()).decode("ascii")
        splitter_state_b64 = bytes(self.workspace_splitter.saveState().toBase64()).decode("ascii")
        self.user_settings = UserSettings(
            output_folder=self.output_folder_path,
            captions_mode=self.captions_mode,
            last_resolution=self.global_selected_resolution,
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
            hotkeys=self.hotkeys,
        )
        self.settings_service.save(self.user_settings)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_ui_settings()
        super().closeEvent(event)

    def _append_log(self, text: str) -> None:
        self.logs_text.append(text)

