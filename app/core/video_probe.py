from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess

from app.core.ffmpeg_locator import build_subprocess_env, resolve_binary


@dataclass
class VideoMetadata:
    path: str
    width: int
    height: int
    fps: float
    duration_seconds: float
    frame_count: int


class VideoProbeError(RuntimeError):
    """Raised when video metadata probing fails."""


def _fps_from_ratio(raw: str) -> float:
    if "/" not in raw:
        return float(raw)
    num, den = raw.split("/", 1)
    denominator = float(den) if float(den) != 0 else 1.0
    return float(num) / denominator


def probe_video(path: str | Path) -> VideoMetadata:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(str(source))
    if not source.is_file():
        raise VideoProbeError(f"Selected path is not a file: {source}")

    cmd = [
        resolve_binary("ffprobe"),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(source),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env=build_subprocess_env(),
        )
    except FileNotFoundError as exc:
        raise VideoProbeError(
            "ffprobe is not found.\n"
            "Place ffprobe.exe in project bin folder or install FFmpeg and add it to PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise VideoProbeError(
            "Failed to probe video with ffprobe.\n"
            f"Details: {stderr or 'unknown ffprobe error'}"
        ) from exc

    raw_output = result.stdout
    if not raw_output:
        # Some ffprobe builds may emit json to stderr even with -print_format json.
        raw_output = result.stderr
    if not raw_output:
        raise VideoProbeError(
            "ffprobe returned empty metadata output.\n"
            f"Source: {source}\n"
            "Please verify the selected video file and ffprobe build."
        )
    try:
        payload = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError) as exc:
        raise VideoProbeError("ffprobe returned invalid metadata output.") from exc
    video_stream = next(
        (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise VideoProbeError("No video stream found in selected file.")

    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    fps = _fps_from_ratio(video_stream.get("avg_frame_rate", "0/1"))
    duration_seconds = float(
        video_stream.get("duration", payload.get("format", {}).get("duration", 0))
    )
    stream_frames = video_stream.get("nb_frames")
    if stream_frames and int(stream_frames) > 0:
        frame_count = int(stream_frames)
    else:
        frame_count = int(round(duration_seconds * fps))

    return VideoMetadata(
        path=str(source),
        width=width,
        height=height,
        fps=fps,
        duration_seconds=duration_seconds,
        frame_count=frame_count,
    )

