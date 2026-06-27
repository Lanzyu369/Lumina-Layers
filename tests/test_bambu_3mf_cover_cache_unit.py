"""Unit tests for 3MF cover thumbnail runtime caching."""

from __future__ import annotations

import os

from PIL import Image


def _write_cover(path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (32, 24), color).save(path)


def test_cover_thumbnail_builder_reuses_cached_path_bundle(tmp_path, monkeypatch):
    """Repeated unchanged path sources should not be decoded again."""
    from utils import bambu_3mf_cover as cover

    cover_path = tmp_path / "cover.png"
    _write_cover(cover_path, (255, 0, 0))
    cover.clear_cover_thumbnail_cache()

    original_decode = cover._decode_source
    calls = {"count": 0}

    def _counting_decode(source):
        calls["count"] += 1
        return original_decode(source)

    monkeypatch.setattr(cover, "_decode_source", _counting_decode)

    builder = cover.CoverThumbnailBuilder()
    first = builder.build(str(cover_path))
    second = builder.build(str(cover_path))

    assert calls["count"] == 1
    assert first.thumbnail_3mf == second.thumbnail_3mf
    assert first.plate_main == second.plate_main


def test_cover_thumbnail_builder_invalidates_cached_path_when_file_changes(tmp_path, monkeypatch):
    """A changed cover image at the same path must rebuild the PNG bundle."""
    from utils import bambu_3mf_cover as cover

    cover_path = tmp_path / "cover.png"
    _write_cover(cover_path, (255, 0, 0))
    first_mtime_ns = os.stat(cover_path).st_mtime_ns
    cover.clear_cover_thumbnail_cache()

    original_decode = cover._decode_source
    calls = {"count": 0}

    def _counting_decode(source):
        calls["count"] += 1
        return original_decode(source)

    monkeypatch.setattr(cover, "_decode_source", _counting_decode)

    builder = cover.CoverThumbnailBuilder()
    first = builder.build(str(cover_path))
    _write_cover(cover_path, (0, 0, 255))
    changed_mtime_ns = first_mtime_ns + 1_000_000_000
    os.utime(cover_path, ns=(changed_mtime_ns, changed_mtime_ns))
    second = builder.build(str(cover_path))

    assert calls["count"] == 2
    assert first.thumbnail_3mf != second.thumbnail_3mf
