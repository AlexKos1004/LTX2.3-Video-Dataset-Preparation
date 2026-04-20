from __future__ import annotations

from dataclasses import dataclass


def is_valid_8n_plus_1(frame_count: int) -> bool:
    return frame_count > 0 and (frame_count - 1) % 8 == 0


def normalize_8n_plus_1(frame_count: int, mode: str = "floor") -> int:
    if frame_count <= 1:
        return 1
    if mode == "ceil":
        remainder = (frame_count - 1) % 8
        return frame_count if remainder == 0 else frame_count + (8 - remainder)
    return ((frame_count - 1) // 8) * 8 + 1


def is_multiple_of_32(value: int) -> bool:
    return value > 0 and value % 32 == 0


def normalize_multiple_of_32(value: int, mode: str = "floor") -> int:
    if value <= 0:
        return 32
    if mode == "ceil":
        return ((value + 31) // 32) * 32
    return max(32, (value // 32) * 32)


@dataclass
class CropRect:
    x: int
    y: int
    width: int
    height: int


def clamp_crop_rect(
    crop: CropRect,
    source_width: int,
    source_height: int,
) -> CropRect:
    width = min(normalize_multiple_of_32(crop.width, mode="floor"), source_width)
    height = min(normalize_multiple_of_32(crop.height, mode="floor"), source_height)
    width = normalize_multiple_of_32(width, mode="floor")
    height = normalize_multiple_of_32(height, mode="floor")

    max_x = max(0, source_width - width)
    max_y = max(0, source_height - height)
    x = min(max(crop.x, 0), max_x)
    y = min(max(crop.y, 0), max_y)
    return CropRect(x=x, y=y, width=width, height=height)

