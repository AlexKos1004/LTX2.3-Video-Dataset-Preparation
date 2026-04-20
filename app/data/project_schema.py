from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass
class CropRect:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


@dataclass
class ClipDefinition:
    clip_name: str
    start_seconds: float
    duration_seconds: float
    target_width: int
    target_height: int
    crop: CropRect
    tags_line: str = ""
    resize_percent: int = 100
    resize_width: int = 0
    resize_height: int = 0


@dataclass
class VideoAsset:
    source_video_path: str = ""
    selected_resolution: str = "960x544"
    current_resize_percent: int = 100
    current_crop: CropRect = field(default_factory=CropRect)
    clips: list[ClipDefinition] = field(default_factory=list)


@dataclass
class VideoProject:
    output_folder: str = ""
    captions_mode: str = "same_folder"
    selected_resolution: str = "960x544"
    selected_tagger: str = "wd14"
    caption_prefix: str = ""
    manual_keywords_line: str = ""
    videos: list[VideoAsset] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VideoProject":
        videos_payload = payload.get("videos", [])
        if not videos_payload and payload.get("source_video_path"):
            # Backward compatibility: old single-video schema.
            videos_payload = [
                {
                    "source_video_path": payload.get("source_video_path", ""),
                    "selected_resolution": payload.get("selected_resolution", "960x544"),
                    "current_resize_percent": payload.get("current_resize_percent", 100),
                    "current_crop": payload.get("current_crop", {}),
                    "clips": payload.get("clips", []),
                }
            ]

        videos: list[VideoAsset] = []
        for video_payload in videos_payload:
            video_clips: list[ClipDefinition] = []
            for clip_dict in video_payload.get("clips", []):
                crop_payload = clip_dict.get("crop", {})
                video_clips.append(
                    ClipDefinition(
                        clip_name=clip_dict.get("clip_name", ""),
                        start_seconds=float(clip_dict.get("start_seconds", 0)),
                        duration_seconds=float(clip_dict.get("duration_seconds", 0)),
                        target_width=int(clip_dict.get("target_width", 0)),
                        target_height=int(clip_dict.get("target_height", 0)),
                        crop=CropRect(
                            x=int(crop_payload.get("x", 0)),
                            y=int(crop_payload.get("y", 0)),
                            width=int(crop_payload.get("width", 0)),
                            height=int(crop_payload.get("height", 0)),
                        ),
                        tags_line=clip_dict.get("tags_line", ""),
                        resize_percent=int(clip_dict.get("resize_percent", 100)),
                        resize_width=int(clip_dict.get("resize_width", 0)),
                        resize_height=int(clip_dict.get("resize_height", 0)),
                    )
                )
            current_crop_payload = video_payload.get("current_crop", {})
            videos.append(
                VideoAsset(
                    source_video_path=video_payload.get("source_video_path", ""),
                    selected_resolution=video_payload.get("selected_resolution", "960x544"),
                    current_resize_percent=int(video_payload.get("current_resize_percent", 100)),
                    current_crop=CropRect(
                        x=int(current_crop_payload.get("x", 0)),
                        y=int(current_crop_payload.get("y", 0)),
                        width=int(current_crop_payload.get("width", 0)),
                        height=int(current_crop_payload.get("height", 0)),
                    ),
                    clips=video_clips,
                )
            )

        selected_resolution = payload.get("selected_resolution", "")
        if not selected_resolution and videos:
            selected_resolution = videos[0].selected_resolution
        if not selected_resolution:
            selected_resolution = payload.get("last_resolution", "960x544")

        return cls(
            output_folder=payload.get("output_folder", ""),
            captions_mode=payload.get("captions_mode", "same_folder"),
            selected_resolution=selected_resolution,
            selected_tagger=payload.get("selected_tagger", "wd14"),
            caption_prefix=payload.get("caption_prefix", ""),
            manual_keywords_line=payload.get("manual_keywords_line", ""),
            videos=videos,
            keywords=list(payload.get("keywords", [])),
        )


def save_project(project: VideoProject, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(project.to_dict(), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def load_project(path: str | Path) -> VideoProject:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return VideoProject.from_dict(payload)

