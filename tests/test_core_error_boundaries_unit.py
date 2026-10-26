"""Core error boundary unit tests."""

from __future__ import annotations

import pytest

from core.errors import CoreProcessingError
from core.extractor import manual_fix_cell


def test_manual_fix_cell_wraps_unexpected_error_to_core_processing_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Unexpected internals should be wrapped as CoreProcessingError."""
    lut_path = tmp_path / "lut.json"
    lut_path.write_text("{}", encoding="utf-8")

    def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "core.extractor.LUTManager.load_lut_with_metadata",
        _boom,
    )

    with pytest.raises(CoreProcessingError):
        manual_fix_cell((0, 0), "#112233", str(lut_path))
