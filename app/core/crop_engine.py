from __future__ import annotations

from app.core.clip_rules import CropRect, clamp_crop_rect


def make_default_crop(source_width: int, source_height: int) -> CropRect:
    return clamp_crop_rect(
        CropRect(x=0, y=0, width=source_width, height=source_height),
        source_width=source_width,
        source_height=source_height,
    )


def normalize_crop(
    x: int,
    y: int,
    width: int,
    height: int,
    source_width: int,
    source_height: int,
) -> CropRect:
    return clamp_crop_rect(
        CropRect(x=x, y=y, width=width, height=height),
        source_width=source_width,
        source_height=source_height,
    )

