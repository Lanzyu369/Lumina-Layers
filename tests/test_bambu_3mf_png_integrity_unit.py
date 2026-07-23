"""Regression tests for 3MF preview PNG integrity.

Background (LL-1296): the writer previously shipped a hardcoded 68-byte
``1x1 transparent PNG`` placeholder whose ``IDAT`` chunk CRC was incorrect.
Bambu Studio and Orca-family slicers silently ignored malformed thumbnails
and rendered a blank tile, but Anycubic Slicer Next decoded every
``Metadata/*.png`` eagerly on import and crashed (``Application Hang``) on
the bad CRC. These tests lock the contract that every preview PNG embedded
into an exported 3MF must round-trip through ``PIL.Image.verify()``.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image, UnidentifiedImageError

from helpers_threemf_manifest import cleanup_paths, export_fixture_3mf
from utils.bambu_3mf_writer import BambuStudio3MFWriter


SLICER_COVERAGE: list[tuple[str, str, str]] = [
    ("bambu-p1s", "BambuStudio", "0.4"),
    ("bambu-p1s", "OrcaSlicer", "0.4"),
    ("elegoo-cc2", "ElegooSlicer", "0.4"),
    ("snapmaker-u1", "SnapmakerOrca", "0.4"),
    ("anycubic-kobra-x", "AnycubicSlicerNext", "0.4"),
    ("flashforge-ad5x", "FlashStudio", "0.25"),
]


def _assert_png_is_decodable(data: bytes, context: str) -> None:
    """Assert ``data`` is a PNG that ``PIL.Image.verify()`` accepts.

    Parallels the validation path Anycubic Slicer Next runs at import time.
    Also reopens via ``Image.open`` to confirm pixel decoding succeeds,
    because ``verify()`` alone only checks structural CRCs.
    """
    try:
        Image.open(io.BytesIO(data)).verify()
    except (UnidentifiedImageError, SyntaxError, OSError) as exc:
        pytest.fail(f"{context}: PIL.Image.verify() rejected bytes ({len(data)}B): {exc}")

    try:
        with Image.open(io.BytesIO(data)) as reopened:
            reopened.load()
            assert reopened.size[0] >= 1 and reopened.size[1] >= 1, (
                f"{context}: PNG has zero-sized dimensions {reopened.size}"
            )
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"{context}: PNG pixel decode failed: {exc}")


class TestPlaceholderPngHelper:
    """Direct contract tests on the placeholder factory itself."""

    def test_placeholder_starts_with_png_signature(self) -> None:
        data = BambuStudio3MFWriter._build_preview_placeholder_png_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", "Placeholder does not start with PNG signature"

    def test_placeholder_passes_pil_verify(self) -> None:
        data = BambuStudio3MFWriter._build_preview_placeholder_png_bytes()
        _assert_png_is_decodable(data, context="placeholder factory")

    def test_placeholder_is_cached_across_calls(self) -> None:
        a = BambuStudio3MFWriter._build_preview_placeholder_png_bytes()
        b = BambuStudio3MFWriter._build_preview_placeholder_png_bytes()
        assert a is b, "Placeholder PNG bytes should be memoized at module level"


class TestExportedPreviewPngsAreValid:
    """End-to-end: every Metadata/*.png in an exported 3MF must decode cleanly."""

    @pytest.mark.parametrize(
        ("printer_id", "slicer", "nozzle_size"),
        SLICER_COVERAGE,
        ids=[f"{p}-{s}-{n}" for p, s, n in SLICER_COVERAGE],
    )
    def test_all_metadata_pngs_decode(
        self,
        printer_id: str,
        slicer: str,
        nozzle_size: str,
    ) -> None:
        output_path = export_fixture_3mf(
            printer_id=printer_id,
            slicer=slicer,
            nozzle_size=nozzle_size,
            case_name="full_palette",
        )
        try:
            with zipfile.ZipFile(output_path, "r") as archive:
                png_entries = [
                    name
                    for name in archive.namelist()
                    if name.startswith("Metadata/") and name.endswith(".png")
                ]
                assert png_entries, (
                    f"{printer_id}/{slicer}/{nozzle_size}: exported 3MF has no "
                    "Metadata/*.png entries (preview wiring broken?)"
                )
                for entry in png_entries:
                    data = archive.read(entry)
                    _assert_png_is_decodable(
                        data,
                        context=f"{printer_id}/{slicer}/{nozzle_size}::{entry}",
                    )
        finally:
            cleanup_paths(Path(output_path))
