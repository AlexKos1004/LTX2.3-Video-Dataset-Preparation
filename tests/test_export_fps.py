from pathlib import Path

from app.core.export_pipeline import ExportPipeline, ExportRequest


def _build_job(tmp_path: Path, forced_fps: int | None) -> ExportRequest:
    return ExportRequest(
        source_video_path="input.mp4",
        output_folder=str(tmp_path),
        clip_name="clip_001",
        start_seconds=0.0,
        duration_seconds=5.0,
        fps=29.97,
        crop_x=0,
        crop_y=0,
        crop_w=448,
        crop_h=768,
        target_width=448,
        target_height=768,
        resize_width=0,
        resize_height=0,
        tags_line="tag1, tag2",
        captions_mode="same_folder",
        forced_fps=forced_fps,
    )


def test_export_uses_forced_fps_exactly(monkeypatch, tmp_path: Path) -> None:
    captured_command: list[str] = []

    def fake_run(command, **_kwargs):
        captured_command[:] = command
        return None

    def fake_caption_writer(video_output_path, tags_line, mode):
        caption_path = Path(video_output_path).with_suffix(".txt")
        caption_path.write_text(tags_line, encoding="utf-8")
        return caption_path

    monkeypatch.setattr("app.core.export_pipeline.resolve_binary", lambda _name: "ffmpeg")
    monkeypatch.setattr("app.core.export_pipeline.subprocess.run", fake_run)
    monkeypatch.setattr("app.core.export_pipeline.write_caption_txt", fake_caption_writer)

    pipeline = ExportPipeline()
    for fps in (8, 16, 24):
        captured_command.clear()
        pipeline.export_one(_build_job(tmp_path, forced_fps=fps))
        assert "-r" in captured_command
        fps_index = captured_command.index("-r") + 1
        assert captured_command[fps_index] == str(fps)


def test_export_without_forced_fps_uses_source_fps_rounding(monkeypatch, tmp_path: Path) -> None:
    captured_command: list[str] = []

    def fake_run(command, **_kwargs):
        captured_command[:] = command
        return None

    def fake_caption_writer(video_output_path, tags_line, mode):
        caption_path = Path(video_output_path).with_suffix(".txt")
        caption_path.write_text(tags_line, encoding="utf-8")
        return caption_path

    monkeypatch.setattr("app.core.export_pipeline.resolve_binary", lambda _name: "ffmpeg")
    monkeypatch.setattr("app.core.export_pipeline.subprocess.run", fake_run)
    monkeypatch.setattr("app.core.export_pipeline.write_caption_txt", fake_caption_writer)

    pipeline = ExportPipeline()
    pipeline.export_one(_build_job(tmp_path, forced_fps=None))
    assert "-r" in captured_command
    fps_index = captured_command.index("-r") + 1
    assert captured_command[fps_index] == "30"
