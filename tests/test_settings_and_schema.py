from pathlib import Path

from app.core.settings_service import SettingsService, UserSettings
from app.data.project_schema import ClipDefinition, CropRect, VideoProject, load_project, save_project


def test_settings_persist(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "settings.json")
    service.save(
        UserSettings(
            output_folder="E:/dataset/output",
            captions_mode="captions",
            last_resolution="960x544 (Base)",
        )
    )
    loaded = service.load()
    assert loaded.output_folder == "E:/dataset/output"
    assert loaded.captions_mode == "captions"


def test_project_schema_round_trip(tmp_path: Path) -> None:
    project = VideoProject(
        source_video_path="video.mp4",
        output_folder="out",
        captions_mode="same_folder",
        selected_resolution="960x544 (Base)",
        clips=[
            ClipDefinition(
                clip_name="video_001",
                start_seconds=0.0,
                duration_seconds=5.0,
                target_width=960,
                target_height=544,
                crop=CropRect(x=0, y=0, width=960, height=544),
                tags_line="tag1, tag2",
            )
        ],
        keywords=["tag1", "tag2"],
    )
    file_path = tmp_path / "project.json"
    save_project(project, file_path)
    loaded = load_project(file_path)
    assert loaded.source_video_path == "video.mp4"
    assert loaded.clips[0].clip_name == "video_001"
    assert loaded.clips[0].tags_line == "tag1, tag2"

