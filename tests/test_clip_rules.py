from app.core.clip_rules import (
    CropRect,
    clamp_crop_rect,
    is_multiple_of_32,
    is_valid_8n_plus_1,
    normalize_8n_plus_1,
)


def test_is_valid_8n_plus_1() -> None:
    assert is_valid_8n_plus_1(1)
    assert is_valid_8n_plus_1(9)
    assert not is_valid_8n_plus_1(8)


def test_normalize_8n_plus_1_floor() -> None:
    assert normalize_8n_plus_1(26, mode="floor") == 25
    assert normalize_8n_plus_1(25, mode="floor") == 25


def test_multiple_of_32() -> None:
    assert is_multiple_of_32(32)
    assert not is_multiple_of_32(48)


def test_clamp_crop_rect() -> None:
    rect = clamp_crop_rect(
        CropRect(x=50, y=20, width=1003, height=777),
        source_width=1280,
        source_height=720,
    )
    assert rect.width % 32 == 0
    assert rect.height % 32 == 0
    assert rect.x >= 0
    assert rect.y >= 0

