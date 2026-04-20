from __future__ import annotations

from pathlib import Path


def caption_target_dir(video_output_dir: Path, mode: str) -> Path:
    if mode == "captions":
        target = video_output_dir / "captions"
        target.mkdir(parents=True, exist_ok=True)
        return target
    return video_output_dir


def write_caption_txt(
    video_output_path: str | Path,
    tags_line: str,
    mode: str = "same_folder",
) -> Path:
    video_path = Path(video_output_path)
    target_dir = caption_target_dir(video_path.parent, mode)
    txt_path = target_dir / f"{video_path.stem}.txt"
    txt_path.write_text(tags_line.strip(), encoding="utf-8")
    return txt_path

