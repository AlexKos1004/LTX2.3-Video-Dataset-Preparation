from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from app.core.caption_writer import write_caption_txt
from app.core.clip_rules import normalize_8n_plus_1
from app.core.ffmpeg_locator import build_subprocess_env, resolve_binary


@dataclass
class ExportRequest:
    source_video_path: str
    output_folder: str
    clip_name: str
    start_seconds: float
    duration_seconds: float
    fps: float
    crop_x: int
    crop_y: int
    crop_w: int
    crop_h: int
    target_width: int
    target_height: int
    resize_width: int
    resize_height: int
    tags_line: str
    captions_mode: str


@dataclass
class ExportResult:
    video_path: str
    caption_path: str


class ExportPipeline:
    def export_many(
        self,
        jobs: list[ExportRequest],
        on_progress: callable | None = None,
    ) -> list[ExportResult]:
        results: list[ExportResult] = []
        total = max(1, len(jobs))
        for index, job in enumerate(jobs, start=1):
            result = self.export_one(job)
            results.append(result)
            if on_progress:
                on_progress(index, total, result.video_path)
        return results

    def export_one(self, job: ExportRequest) -> ExportResult:
        output_dir = Path(job.output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_video = output_dir / f"{job.clip_name}.mp4"

        desired_frames = int(round(job.duration_seconds * job.fps))
        valid_frames = normalize_8n_plus_1(desired_frames, mode="floor")
        valid_duration = max(valid_frames / max(job.fps, 1e-9), 1 / max(job.fps, 1e-9))

        filters: list[str] = []
        if job.resize_width > 0 and job.resize_height > 0:
            filters.append(f"scale={job.resize_width}:{job.resize_height}")
        filters.append(f"crop={job.crop_w}:{job.crop_h}:{job.crop_x}:{job.crop_y}")
        if job.crop_w != job.target_width or job.crop_h != job.target_height:
            filters.append(f"scale={job.target_width}:{job.target_height}")
        vf = ",".join(filters)

        command = [
            resolve_binary("ffmpeg"),
            "-y",
            "-ss",
            f"{job.start_seconds:.6f}",
            "-i",
            job.source_video_path,
            "-t",
            f"{valid_duration:.6f}",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-pix_fmt",
            "yuv420p",
            str(output_video),
        ]
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            env=build_subprocess_env(),
        )

        caption_path = write_caption_txt(
            video_output_path=output_video,
            tags_line=job.tags_line,
            mode=job.captions_mode,
        )
        return ExportResult(video_path=str(output_video), caption_path=str(caption_path))

