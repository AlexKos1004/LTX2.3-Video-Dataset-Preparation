from pathlib import Path

from app.core.caption_writer import write_caption_txt


def test_writes_caption_to_same_folder(tmp_path: Path) -> None:
    video = tmp_path / "clip_001.mp4"
    video.write_text("", encoding="utf-8")
    txt = write_caption_txt(video, "tag1, tag2", mode="same_folder")
    assert txt.exists()
    assert txt.name == "clip_001.txt"
    assert txt.read_text(encoding="utf-8") == "tag1, tag2"


def test_writes_caption_to_captions_subfolder(tmp_path: Path) -> None:
    video = tmp_path / "clip_002.mp4"
    video.write_text("", encoding="utf-8")
    txt = write_caption_txt(video, "tag3", mode="captions")
    assert txt.exists()
    assert txt.parent.name == "captions"
    assert txt.name == "clip_002.txt"

