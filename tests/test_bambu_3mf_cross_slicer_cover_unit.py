"""Cross-slicer cover-thumbnail structure + metadata invariant regressions.

中文标题：跨切片器封面缩略图结构 + Metadata 不变量回归测试

These tests cover task 9 of the ``3mf-cover-thumbnail`` spec:

- Five slicer IDs (``BambuStudio`` / ``OrcaSlicer`` / ``SnapmakerOrca`` /
  ``ElegooSlicer`` / ``AnycubicSlicerNext``) all emit structurally complete
  3MF packages: ``[Content_Types].xml`` (single ``png`` ``Default``),
  ``_rels/.rels`` (OPC ``rel-1`` plus three cover relationships whose URIs
  match the Glossary), and three ``Auxiliaries/.thumbnails/*.png`` parts.
- ``Metadata/model_settings.config`` / ``project_settings.config`` /
  ``slice_info.config`` byte-equality across ``cover_source=None`` vs
  real-image variants — only PNG byte assets driven by ``cover_source`` are
  allowed to differ. There is no on-disk baseline; the strategy is to drive
  two exports with the same logical inputs and confirm config bytes are
  identical regardless of ``cover_source`` value.
- ``cover_source=None`` still emits all three thumbnails as legal opaque
  white placeholder PNGs and keeps three cover relationship entries in
  ``_rels/.rels`` (no half-baked outputs).

Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 10.2 / Properties 1, 5,
6, 8.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from utils.bambu_3mf_cover import COVER_THUMBNAIL_SPECS
from utils.bambu_3mf_writer import BambuStudio3MFWriter


# ---------------------------------------------------------------------------
# Constants & fixtures
# ---------------------------------------------------------------------------


_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

_OPC_THUMBNAIL_TYPE = (
    "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"
)
_BAMBU_COVER_MIDDLE_TYPE = (
    "http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"
)
_BAMBU_COVER_SMALL_TYPE = (
    "http://schemas.bambulab.com/package/2021/cover-thumbnail-small"
)

# (printer_id, slicer) — covers the five slicer IDs accepted by
# ``BambuStudio3MFWriter._get_app_version_str``. The printer_id values match
# templates that ship in the repo (see ``tests/test_bambu_3mf_png_integrity_unit.py``).
SLICER_MATRIX: list[tuple[str, str]] = [
    ("bambu-p1s", "BambuStudio"),
    ("bambu-p1s", "OrcaSlicer"),
    ("snapmaker-u1", "SnapmakerOrca"),
    ("elegoo-cc2", "ElegooSlicer"),
    ("anycubic-kobra-x", "AnycubicSlicerNext"),
]

NOZZLE = "0.4"

# Three Metadata/* configs whose key/value mappings must be cover-source-independent.
_METADATA_CONFIG_PATHS: tuple[str, ...] = (
    "Metadata/model_settings.config",
    "Metadata/project_settings.config",
    "Metadata/slice_info.config",
)

# PNG asset paths that are expected to differ when ``cover_source`` switches
# between ``None`` (white placeholder) and a real image (red letterbox).
_COVER_DRIVEN_PNG_PATHS: frozenset[str] = frozenset(
    {
        "Metadata/plate_1.png",
        "Metadata/plate_no_light_1.png",
        "Auxiliaries/.thumbnails/thumbnail_3mf.png",
        "Auxiliaries/.thumbnails/thumbnail_middle.png",
        "Auxiliaries/.thumbnails/thumbnail_small.png",
    }
)


@pytest.fixture()
def red_source_png(tmp_path: Path) -> Path:
    """Encode a 200×100 solid-red PNG for use as ``cover_source``."""

    path = tmp_path / "source.png"
    Image.new("RGB", (200, 100), (220, 30, 40)).save(path, format="PNG")
    return path


def _build_writer(
    output_path: Path,
    *,
    printer_id: str,
    slicer: str,
    cover_source=None,
) -> BambuStudio3MFWriter:
    """Construct a minimal writer with two distinct meshes (mirrors the
    integration fixture in ``tests/test_bambu_3mf_writer_thumbnail_integration.py``).
    """

    writer = BambuStudio3MFWriter(
        str(output_path),
        settings={},
        color_mode="4-Color",
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=NOZZLE,
        cover_source=cover_source,
    )

    a = trimesh.creation.box(extents=[2, 2, 2])
    a.metadata["bambu_material_name"] = "White"
    writer.add_mesh(a, "White", (255, 255, 255))

    b = trimesh.creation.box(extents=[2, 2, 2])
    b.apply_translation([4, 0, 0])
    b.metadata["bambu_material_name"] = "Red"
    writer.add_mesh(b, "Red", (220, 30, 40))
    return writer


def _export(
    out_path: Path,
    *,
    printer_id: str,
    slicer: str,
    cover_source,
) -> None:
    _build_writer(
        out_path,
        printer_id=printer_id,
        slicer=slicer,
        cover_source=cover_source,
    ).export()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_rels_root(zf: zipfile.ZipFile) -> ET.Element:
    return ET.fromstring(zf.read("_rels/.rels"))


def _iter_relationships(root: ET.Element) -> list[ET.Element]:
    """Return all ``<Relationship>`` children regardless of namespace usage."""

    namespaced = root.findall(f"{{{_RELS_NS}}}Relationship")
    if namespaced:
        return namespaced
    return root.findall("Relationship")


def _decode_png(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _verify_png(data: bytes) -> None:
    Image.open(io.BytesIO(data)).verify()


def _cover_relationships_by_type(zf: zipfile.ZipFile) -> dict[str, ET.Element]:
    rels = _iter_relationships(_read_rels_root(zf))
    return {
        rel.get("Type"): rel
        for rel in rels
        if rel.get("Target", "").startswith("/Auxiliaries/.thumbnails/")
    }


# ---------------------------------------------------------------------------
# 1) Cross-slicer structural regression
# ---------------------------------------------------------------------------


class TestCrossSlicerStructure:
    """Five slicer IDs each emit a structurally complete 3MF package."""

    @pytest.mark.parametrize(
        ("printer_id", "slicer"),
        SLICER_MATRIX,
        ids=[s for _, s in SLICER_MATRIX],
    )
    def test_three_thumbnail_pngs_present_and_decodable(
        self,
        tmp_path: Path,
        red_source_png: Path,
        printer_id: str,
        slicer: str,
    ) -> None:
        out = tmp_path / f"{slicer}.3mf"
        _export(
            out,
            printer_id=printer_id,
            slicer=slicer,
            cover_source=str(red_source_png),
        )
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            for spec in COVER_THUMBNAIL_SPECS:
                assert spec.zip_path in names, (
                    f"{slicer}: missing {spec.zip_path}"
                )
                payload = zf.read(spec.zip_path)
                _verify_png(payload)
                decoded = _decode_png(payload)
                assert decoded.size == (spec.width, spec.height)
                assert decoded.mode == "RGB"

    @pytest.mark.parametrize(
        ("printer_id", "slicer"),
        SLICER_MATRIX,
        ids=[s for _, s in SLICER_MATRIX],
    )
    def test_content_types_png_default_is_unique(
        self,
        tmp_path: Path,
        red_source_png: Path,
        printer_id: str,
        slicer: str,
    ) -> None:
        out = tmp_path / f"{slicer}.3mf"
        _export(
            out,
            printer_id=printer_id,
            slicer=slicer,
            cover_source=str(red_source_png),
        )
        with zipfile.ZipFile(out) as zf:
            root = ET.fromstring(zf.read("[Content_Types].xml"))
        png_defaults = [
            child
            for child in root.findall(f"{{{_CT_NS}}}Default")
            if child.get("Extension", "").lower() == "png"
        ]
        assert len(png_defaults) == 1, (
            f"{slicer}: expected exactly one png Default, got {len(png_defaults)}"
        )
        assert png_defaults[0].get("ContentType") == "image/png"

    @pytest.mark.parametrize(
        ("printer_id", "slicer"),
        SLICER_MATRIX,
        ids=[s for _, s in SLICER_MATRIX],
    )
    def test_rels_has_opc_plus_two_bambu_cover_relationships_with_glossary_uris(
        self,
        tmp_path: Path,
        red_source_png: Path,
        printer_id: str,
        slicer: str,
    ) -> None:
        out = tmp_path / f"{slicer}.3mf"
        _export(
            out,
            printer_id=printer_id,
            slicer=slicer,
            cover_source=str(red_source_png),
        )
        with zipfile.ZipFile(out) as zf:
            cover_rels = _cover_relationships_by_type(zf)

        # Three cover relationships keyed by glossary-exact Type URI.
        assert set(cover_rels.keys()) == {
            _OPC_THUMBNAIL_TYPE,
            _BAMBU_COVER_MIDDLE_TYPE,
            _BAMBU_COVER_SMALL_TYPE,
        }, f"{slicer}: cover rel Types do not match glossary"

        # Targets exactly match the spec.
        assert (
            cover_rels[_OPC_THUMBNAIL_TYPE].get("Target")
            == "/Auxiliaries/.thumbnails/thumbnail_3mf.png"
        )
        assert (
            cover_rels[_BAMBU_COVER_MIDDLE_TYPE].get("Target")
            == "/Auxiliaries/.thumbnails/thumbnail_middle.png"
        )
        assert (
            cover_rels[_BAMBU_COVER_SMALL_TYPE].get("Target")
            == "/Auxiliaries/.thumbnails/thumbnail_small.png"
        )

    @pytest.mark.parametrize(
        ("printer_id", "slicer"),
        SLICER_MATRIX,
        ids=[s for _, s in SLICER_MATRIX],
    )
    def test_existing_3dmodel_relationship_preserved(
        self,
        tmp_path: Path,
        red_source_png: Path,
        printer_id: str,
        slicer: str,
    ) -> None:
        out = tmp_path / f"{slicer}.3mf"
        _export(
            out,
            printer_id=printer_id,
            slicer=slicer,
            cover_source=str(red_source_png),
        )
        with zipfile.ZipFile(out) as zf:
            rels = _iter_relationships(_read_rels_root(zf))
        # rel-1 entry pointing at /3D/3dmodel.model must still exist.
        targets_3dmodel = [
            rel for rel in rels if rel.get("Target") == "/3D/3dmodel.model"
        ]
        assert len(targets_3dmodel) == 1, (
            f"{slicer}: rel-1 (/3D/3dmodel.model) must remain after rels rewrite"
        )
        # Total of 4 relationships (rel-1 + three cover relations).
        assert len(rels) == 4, f"{slicer}: expected 4 relationships, got {len(rels)}"
        # All Ids unique.
        ids = [rel.get("Id") for rel in rels]
        assert len(set(ids)) == len(ids), f"{slicer}: duplicate Id values: {ids}"


# ---------------------------------------------------------------------------
# 2) Metadata invariants regression
# ---------------------------------------------------------------------------


class TestMetadataInvariantsAcrossCoverSource:
    """Three Metadata/*.config files are identical regardless of cover_source.

    Strategy (per task 9 notes): rather than relying on an on-disk baseline,
    we drive two exports with the same logical inputs — one with
    ``cover_source=None`` and one with a real PNG path — then byte-compare
    the three config files. The plate PNG bytes (and the three
    ``Auxiliaries/.thumbnails/*.png`` parts) are the only assets allowed to
    differ across the two variants.
    """

    @pytest.mark.parametrize(
        ("printer_id", "slicer"),
        SLICER_MATRIX,
        ids=[s for _, s in SLICER_MATRIX],
    )
    def test_three_configs_byte_identical_across_cover_source_variants(
        self,
        tmp_path: Path,
        red_source_png: Path,
        printer_id: str,
        slicer: str,
    ) -> None:
        # Use the same output basename in different subdirectories so
        # ``Metadata/model_settings.config``'s ``source_file`` value (derived
        # from ``os.path.basename(self.output_path)``) is identical across
        # the two exports — only ``cover_source`` should drive byte differences.
        with_dir = tmp_path / "with"
        silent_dir = tmp_path / "silent"
        with_dir.mkdir()
        silent_dir.mkdir()
        with_cover = with_dir / "out.3mf"
        silent = silent_dir / "out.3mf"
        _export(
            with_cover,
            printer_id=printer_id,
            slicer=slicer,
            cover_source=str(red_source_png),
        )
        _export(
            silent, printer_id=printer_id, slicer=slicer, cover_source=None
        )

        with zipfile.ZipFile(with_cover) as a_zf, zipfile.ZipFile(silent) as b_zf:
            a_names = set(a_zf.namelist())
            b_names = set(b_zf.namelist())
            for cp in _METADATA_CONFIG_PATHS:
                assert cp in a_names, f"{slicer}: missing {cp} in with-cover export"
                assert cp in b_names, f"{slicer}: missing {cp} in silent export"
                a_bytes = a_zf.read(cp)
                b_bytes = b_zf.read(cp)
                assert a_bytes == b_bytes, (
                    f"{slicer}: {cp} bytes differ between cover_source variants — "
                    "metadata must not depend on cover_source value"
                )

    @pytest.mark.parametrize(
        ("printer_id", "slicer"),
        SLICER_MATRIX,
        ids=[s for _, s in SLICER_MATRIX],
    )
    def test_only_cover_driven_png_bytes_differ_between_variants(
        self,
        tmp_path: Path,
        red_source_png: Path,
        printer_id: str,
        slicer: str,
    ) -> None:
        # Same-basename strategy as the previous test so the only differences
        # the diff can surface are real cover-driven bytes, not the
        # ``source_file`` metadata key.
        with_dir = tmp_path / "with"
        silent_dir = tmp_path / "silent"
        with_dir.mkdir()
        silent_dir.mkdir()
        with_cover = with_dir / "out.3mf"
        silent = silent_dir / "out.3mf"
        _export(
            with_cover,
            printer_id=printer_id,
            slicer=slicer,
            cover_source=str(red_source_png),
        )
        _export(
            silent, printer_id=printer_id, slicer=slicer, cover_source=None
        )

        with zipfile.ZipFile(with_cover) as a_zf, zipfile.ZipFile(silent) as b_zf:
            a_names = set(a_zf.namelist())
            b_names = set(b_zf.namelist())
            assert a_names == b_names, (
                f"{slicer}: ZIP entry name sets differ between cover variants: "
                f"only in with-cover={a_names - b_names}, only in silent={b_names - a_names}"
            )

            differing: set[str] = set()
            for name in sorted(a_names):
                if a_zf.read(name) != b_zf.read(name):
                    differing.add(name)

        unexpected = differing - _COVER_DRIVEN_PNG_PATHS
        assert unexpected == set(), (
            f"{slicer}: unexpected non-cover-driven differences between exports: "
            f"{sorted(unexpected)}"
        )


# ---------------------------------------------------------------------------
# 3) cover_source=None placeholder validity
# ---------------------------------------------------------------------------


class TestSilentPlaceholderAcrossSlicers:
    """``cover_source=None`` produces legal white-background placeholder PNGs.

    When the writer is called with ``cover_source=None`` (e.g. calibration /
    kit / recipe-swatch paths), the three ``Auxiliaries/.thumbnails/*.png``
    parts must still be present, must each be a valid RGB PNG sized to the
    target spec, must contain only opaque white pixels (so the slicer never
    sees a half-baked thumbnail), and ``_rels/.rels`` must still expose the
    three cover relationships pointing at them.
    """

    @pytest.mark.parametrize(
        ("printer_id", "slicer"),
        SLICER_MATRIX,
        ids=[s for _, s in SLICER_MATRIX],
    )
    def test_three_thumbnails_are_legal_white_placeholders(
        self,
        tmp_path: Path,
        printer_id: str,
        slicer: str,
    ) -> None:
        out = tmp_path / f"{slicer}-silent.3mf"
        _export(
            out, printer_id=printer_id, slicer=slicer, cover_source=None
        )
        with zipfile.ZipFile(out) as zf:
            for spec in COVER_THUMBNAIL_SPECS:
                payload = zf.read(spec.zip_path)
                _verify_png(payload)
                decoded = _decode_png(payload)
                assert decoded.size == (spec.width, spec.height), (
                    f"{slicer}/{spec.logical_name}: size mismatch"
                )
                assert decoded.mode == "RGB", (
                    f"{slicer}/{spec.logical_name}: mode is {decoded.mode}, expected RGB"
                )
                pixels = np.asarray(decoded)
                assert pixels.shape == (spec.height, spec.width, 3)
                # Pure-white placeholder: every pixel is exactly (255, 255, 255).
                assert np.all(pixels == 255), (
                    f"{slicer}/{spec.logical_name}: placeholder is not pure white "
                    f"(min={int(pixels.min())}, max={int(pixels.max())})"
                )

    @pytest.mark.parametrize(
        ("printer_id", "slicer"),
        SLICER_MATRIX,
        ids=[s for _, s in SLICER_MATRIX],
    )
    def test_silent_export_still_writes_three_cover_relationships(
        self,
        tmp_path: Path,
        printer_id: str,
        slicer: str,
    ) -> None:
        out = tmp_path / f"{slicer}-silent.3mf"
        _export(
            out, printer_id=printer_id, slicer=slicer, cover_source=None
        )
        with zipfile.ZipFile(out) as zf:
            cover_rels = _cover_relationships_by_type(zf)
        # All three cover relationships still present — no degraded output.
        assert set(cover_rels.keys()) == {
            _OPC_THUMBNAIL_TYPE,
            _BAMBU_COVER_MIDDLE_TYPE,
            _BAMBU_COVER_SMALL_TYPE,
        }, (
            f"{slicer}: silent placeholder must still expose all three cover "
            f"relationships, got {sorted(cover_rels.keys())}"
        )
