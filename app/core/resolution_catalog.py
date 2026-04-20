from __future__ import annotations


def build_resolution_catalog() -> list[tuple[int, int]]:
    # 20 values from smaller than base to larger than base.
    width_units = range(20, 40)  # 20 items
    resolutions: list[tuple[int, int]] = []
    for unit in width_units:
        width = unit * 32
        height_units = max(1, round(unit * 17 / 30))
        height = height_units * 32
        resolutions.append((width, height))
    return resolutions


def as_dropdown_items() -> list[str]:
    values = []
    for width, height in build_resolution_catalog():
        label = f"{width}x{height}"
        if width == 960 and height == 544:
            label += " (Base)"
        values.append(label)
    return values


def filter_available_for_source(
    source_width: int,
    source_height: int,
) -> list[tuple[int, int, bool]]:
    filtered = []
    for width, height in build_resolution_catalog():
        allowed = width <= source_width and height <= source_height
        filtered.append((width, height, allowed))
    return filtered

