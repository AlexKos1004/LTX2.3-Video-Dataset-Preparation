from pathlib import Path

from app.core.settings_service import SettingsService, UserSettings
import json

from app.data.project_schema import ClipDefinition, CropRect, VideoAsset, VideoProject, load_project, save_project


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
        output_folder="out",
        captions_mode="same_folder",
        videos=[
            VideoAsset(
                source_video_path="video.mp4",
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
            )
        ],
        keywords=["tag1", "tag2"],
    )
    file_path = tmp_path / "project.json"
    save_project(project, file_path)
    loaded = load_project(file_path)
    assert loaded.videos[0].source_video_path == "video.mp4"
    assert loaded.videos[0].clips[0].clip_name == "video_001"
    assert loaded.videos[0].clips[0].tags_line == "tag1, tag2"


def test_project_schema_loads_legacy_single_video_format(tmp_path: Path) -> None:
    file_path = tmp_path / "legacy_project.json"
    legacy_payload = {
        "source_video_path": "legacy.mp4",
        "output_folder": "out",
        "captions_mode": "same_folder",
        "selected_resolution": "960x544 (Base)",
        "clips": [
            {
                "clip_name": "legacy_001",
                "start_seconds": 1.0,
                "duration_seconds": 4.0,
                "target_width": 960,
                "target_height": 544,
                "crop": {"x": 0, "y": 0, "width": 960, "height": 544},
                "tags_line": "a, b",
            }
        ],
    }
    file_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    loaded = load_project(file_path)
    assert len(loaded.videos) == 1
    assert loaded.videos[0].source_video_path == "legacy.mp4"
    assert loaded.videos[0].clips[0].clip_name == "legacy_001"

