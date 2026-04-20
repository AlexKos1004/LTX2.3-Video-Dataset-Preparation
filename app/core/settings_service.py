from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json


@dataclass
class UserSettings:
    output_folder: str = ""
    captions_mode: str = "same_folder"
    last_resolution: str = "960x544 (Base)"
    last_tagger: str = "wd14"
    window_geometry_b64: str = ""
    window_state_b64: str = ""
    main_window_maximized: bool = False
    crop_dock_visible: bool = True
    caption_dock_visible: bool = True
    logs_dock_visible: bool = True
    preview_dock_visible: bool = True
    timeline_dock_visible: bool = True
    workspace_splitter_state_b64: str = ""
    volume_percent: int = 100
    hotkeys: dict[str, str] = field(default_factory=dict)


class SettingsService:
    def __init__(self, settings_path: str | Path | None = None) -> None:
        if settings_path is None:
            base_dir = Path.home() / ".ltx23_video_editor"
            base_dir.mkdir(parents=True, exist_ok=True)
            settings_path = base_dir / "settings.json"
        self.settings_path = Path(settings_path)

    def load(self) -> UserSettings:
        if not self.settings_path.exists():
            return UserSettings()
        payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        return UserSettings(
            output_folder=payload.get("output_folder", ""),
            captions_mode=payload.get("captions_mode", "same_folder"),
            last_resolution=payload.get("last_resolution", "960x544 (Base)"),
            last_tagger=payload.get("last_tagger", "wd14"),
            window_geometry_b64=payload.get("window_geometry_b64", ""),
            window_state_b64=payload.get("window_state_b64", ""),
            main_window_maximized=bool(payload.get("main_window_maximized", False)),
            crop_dock_visible=bool(payload.get("crop_dock_visible", True)),
            caption_dock_visible=bool(payload.get("caption_dock_visible", True)),
            logs_dock_visible=bool(payload.get("logs_dock_visible", True)),
            preview_dock_visible=bool(payload.get("preview_dock_visible", True)),
            timeline_dock_visible=bool(payload.get("timeline_dock_visible", True)),
            workspace_splitter_state_b64=payload.get("workspace_splitter_state_b64", ""),
            volume_percent=int(payload.get("volume_percent", 100)),
            hotkeys=dict(payload.get("hotkeys", {})),
        )

    def save(self, settings: UserSettings) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(
                {
                    "output_folder": settings.output_folder,
                    "captions_mode": settings.captions_mode,
                    "last_resolution": settings.last_resolution,
                    "last_tagger": settings.last_tagger,
                    "window_geometry_b64": settings.window_geometry_b64,
                    "window_state_b64": settings.window_state_b64,
                    "main_window_maximized": settings.main_window_maximized,
                    "crop_dock_visible": settings.crop_dock_visible,
                    "caption_dock_visible": settings.caption_dock_visible,
                    "logs_dock_visible": settings.logs_dock_visible,
                    "preview_dock_visible": settings.preview_dock_visible,
                    "timeline_dock_visible": settings.timeline_dock_visible,
                    "workspace_splitter_state_b64": settings.workspace_splitter_state_b64,
                    "volume_percent": settings.volume_percent,
                    "hotkeys": settings.hotkeys,
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )

