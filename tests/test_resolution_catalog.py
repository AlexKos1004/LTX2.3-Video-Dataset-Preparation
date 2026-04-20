from app.core.resolution_catalog import build_resolution_catalog, filter_available_for_source


def test_catalog_has_20_items() -> None:
    values = build_resolution_catalog()
    assert len(values) == 20


def test_catalog_contains_base_resolution() -> None:
    assert (960, 544) in build_resolution_catalog()


def test_source_filter_flags_availability() -> None:
    values = filter_available_for_source(800, 600)
    assert any(not allowed for _, _, allowed in values)
    assert all(isinstance(allowed, bool) for _, _, allowed in values)

