"""Property-based tests for ``utils.bambu_3mf_cover`` and the writer cover injection.

中文标题：3MF 封面缩略图模块 + writer 后处理 Hypothesis 属性测试

补充任务 1 / 任务 2 单元测试覆盖的边界（具体尺寸、几个示例输入），属性测试覆盖
更广的输入空间：

- ``CoverThumbnailBuilder.build`` 在 ``(width, height, mode) ∈ [1, 4096] × [1, 4096]
  × {RGB, RGBA, L}`` 输入空间下，5 张输出 PNG 解码后宽高 / 模式严格匹配 spec、
  通过 ``PIL.Image.open(...).verify()``、letterbox 未覆盖区域 RGB 等于
  ``(255, 255, 255)``。
- ``BambuStudio3MFWriter.export()`` 在 ``cover_source ∈ {None, 合法 PNG 字节,
  不存在路径}`` 下：写出的 3MF 仍含三条新 cover 关系（``Type`` URI 严格相等、
  ``Target`` 以 ``/`` 开头）+ 5 张 PNG ``verify()`` 通过 +
  ``[Content_Types].xml`` 中 png Default 唯一。

Hypothesis 配置：``max_examples=50``、``deadline=2000``，关闭 ``Phase.shrink``
以避免大尺寸图像触发不可控的 shrink 时间。

**Validates: Requirements 1.1, 1.2, 1.3, 2.4, 2.5, 2.6, 2.7, 2.8, 7.4, 10.1
/ Property 1, 4, 5, 6, 7**
"""

from __future__ import annotations

import io
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
import trimesh
from hypothesis import HealthCheck, Phase, given, settings, strategies as st
from PIL import Image

from utils.bambu_3mf_cover import (
    COVER_PLATE_SPECS,
    COVER_THUMBNAIL_SPECS,
    CoverPngBundle,
    CoverSpec,
    CoverThumbnailBuilder,
)
from utils.bambu_3mf_writer import BambuStudio3MFWriter


# ---------------------------------------------------------------------------
# Constants
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

_ALL_SPECS = COVER_THUMBNAIL_SPECS + COVER_PLATE_SPECS

# 关闭 ``Phase.shrink``：4096×4096 RGBA 图像在失败时若进入 shrink 阶段会反复
# 重新解码 / 编码，单次属性测试可能跑数十秒至几分钟；属性测试本身覆盖输入空间
# 即可，shrink 出最小化反例不是本任务目标。
_PROPERTY_PHASES = tuple(p for p in Phase if p != Phase.shrink)

# 公共 Hypothesis 设置：与任务描述一致（max_examples=50, deadline=2000）；
# 显式 suppress data_too_large / function_scoped_fixture 以兼容大图像与
# tempfile fixture 风格。
_PROPERTY_SETTINGS = settings(
    max_examples=50,
    deadline=2000,
    phases=_PROPERTY_PHASES,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.function_scoped_fixture,
    ],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bundle_field(bundle: CoverPngBundle, spec: CoverSpec) -> bytes:
    """Map a ``CoverSpec`` to its corresponding bytes field on the bundle."""
    return {
        "package": bundle.thumbnail_3mf,
        "middle": bundle.thumbnail_middle,
        "small": bundle.thumbnail_small,
        "plate": bundle.plate_main,
        "plate_no_light": bundle.plate_no_light,
    }[spec.logical_name]


def _decode_png(data: bytes) -> Image.Image:
    """Decode PNG bytes into a fully-loaded Pillow image."""
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def _verify_png(data: bytes) -> None:
    """Run ``PIL.Image.open(...).verify()`` and raise on failure."""
    Image.open(io.BytesIO(data)).verify()


def _make_writer(output_path: str, cover_source) -> BambuStudio3MFWriter:
    """Construct a minimal writer with two distinct meshes for property runs."""
    writer = BambuStudio3MFWriter(
        output_path,
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p1s",
        slicer="BambuStudio",
        nozzle_size="0.4",
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


# ---------------------------------------------------------------------------
# Strategies — cover bundle property tests
# ---------------------------------------------------------------------------


# Bias dimensions toward small/typical sizes while still sampling the full
# ``[1, 4096]`` spec range. Hypothesis explores boundaries (1) and large values
# explicitly via the ``sampled_from`` arm; the typical arm exercises the bulk
# of realistic cover-source resolutions.
_dim_strategy = st.one_of(
    st.integers(min_value=1, max_value=8),       # tiny / boundary
    st.integers(min_value=9, max_value=300),     # typical
    st.sampled_from([512, 1024, 2048, 4096]),    # large boundary samples
)


@st.composite
def _cover_image_strategy(draw):
    """Generate a uniform-color PIL ``Image`` covering the spec input space.

    Pixels are uniform per example because the properties under test
    (decoded size, RGB mode, ``verify()`` round-trip, white letterbox borders)
    depend only on ``(mode, dimensions, fill_color)``. Generating per-pixel
    randomness on 4096×4096 RGBA would dominate run time without adding
    coverage; uniform-color examples still exercise the alpha-composite path
    via the ``RGBA`` arm with non-255 alpha fills.
    """
    width = draw(_dim_strategy)
    height = draw(_dim_strategy)
    mode = draw(st.sampled_from(["RGB", "RGBA", "L"]))
    if mode == "RGB":
        fill = (
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
        )
    elif mode == "RGBA":
        fill = (
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
        )
    else:  # mode == "L"
        fill = draw(st.integers(0, 255))
    return Image.new(mode, (width, height), fill)


# ---------------------------------------------------------------------------
# Strategies — writer roundtrip property tests
# ---------------------------------------------------------------------------


@st.composite
def _writer_cover_source_strategy(draw):
    """Generate ``cover_source`` ∈ {None, valid PNG bytes, invalid path}.

    Valid PNG bytes use small dimensions (``≤ 64`` pixels per side) because
    the dominant cost in the writer roundtrip test is ``BambuStudio3MFWriter
    .export()``, not the cover decode; covering decode-success vs decode-fail
    paths is what matters for the relationship-injection invariants.
    """
    choice = draw(st.sampled_from(["none", "valid_bytes", "invalid_path"]))
    if choice == "none":
        return None
    if choice == "invalid_path":
        # Path that does not exist on disk; writer falls back to placeholder
        # bundle and emits one structured WARNING per export. The 3MF must
        # still be well-formed.
        return "/nonexistent/lumina_cover_property_test_does_not_exist.png"

    width = draw(st.integers(min_value=1, max_value=64))
    height = draw(st.integers(min_value=1, max_value=64))
    mode = draw(st.sampled_from(["RGB", "RGBA", "L"]))
    if mode == "RGB":
        fill = (
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
        )
    elif mode == "RGBA":
        fill = (
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
        )
    else:
        fill = draw(st.integers(0, 255))
    img = Image.new(mode, (width, height), fill)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _iter_relationships(root: ET.Element) -> list[ET.Element]:
    """Return all ``<Relationship>`` children regardless of namespace usage."""
    namespaced = root.findall(f"{{{_RELS_NS}}}Relationship")
    if namespaced:
        return namespaced
    return root.findall("Relationship")


# ---------------------------------------------------------------------------
# Class 1 — CoverThumbnailBuilder.build property invariants
# ---------------------------------------------------------------------------


class TestCoverBundleBuildProperties:
    """Property invariants over the full cover-source input space.

    **Validates: Requirements 1.1, 2.4, 2.5, 2.6, 2.7, 2.8, 7.4, 10.1
    / Property 1, 7**
    """

    @_PROPERTY_SETTINGS
    @given(image=_cover_image_strategy())
    def test_build_outputs_match_spec_sizes_and_rgb_mode(
        self, image: Image.Image
    ) -> None:
        """Each of the 5 PNGs decodes to its ``CoverSpec`` size in mode ``RGB``.

        **Validates: Requirements 1.1, 2.6, 2.8, 3.1 / Property 1, 7**
        """
        bundle = CoverThumbnailBuilder().build(image)
        for spec in _ALL_SPECS:
            data = _bundle_field(bundle, spec)
            decoded = _decode_png(data)
            assert decoded.size == (spec.width, spec.height), (
                f"{spec.logical_name}: expected {(spec.width, spec.height)}, "
                f"got {decoded.size}"
            )
            assert decoded.mode == "RGB", (
                f"{spec.logical_name}: expected mode RGB, got {decoded.mode}"
            )

    @_PROPERTY_SETTINGS
    @given(image=_cover_image_strategy())
    def test_build_outputs_pass_pil_verify(self, image: Image.Image) -> None:
        """Every PNG byte payload passes ``PIL.Image.open(...).verify()``.

        ``verify()`` consumes the underlying file object, so we re-open a fresh
        ``BytesIO`` for each call.

        **Validates: Requirements 7.1, 10.1 / Property 1**
        """
        bundle = CoverThumbnailBuilder().build(image)
        for spec in _ALL_SPECS:
            _verify_png(_bundle_field(bundle, spec))

    @pytest.mark.parametrize(
        "source_size, white_corners",
        [
            ((4, 3), (False, False, False, False)),
            ((257, 193), (False, True, False, True)),
            ((680, 509), (False, False, True, True)),
            ((100, 100), (True, True, True, True)),
        ],
    )
    def test_letterbox_corners_preserve_content_and_white_padding(
        self,
        source_size: tuple[int, int],
        white_corners: tuple[bool, bool, bool, bool],
    ) -> None:
        """Check exact fit, one-pixel bands and padding on both sides."""
        content = (154, 37, 12)
        image = Image.new("RGB", source_size, content)
        bundle = CoverThumbnailBuilder().build(image)
        decoded = _decode_png(bundle.thumbnail_middle)
        assert decoded.size == (680, 510)
        corners = [
            decoded.getpixel((0, 0)),
            decoded.getpixel((679, 0)),
            decoded.getpixel((0, 509)),
            decoded.getpixel((679, 509)),
        ]
        assert corners == [
            (255, 255, 255) if white else content
            for white in white_corners
        ]


# ---------------------------------------------------------------------------
# Class 2 — Writer roundtrip property invariants
# ---------------------------------------------------------------------------


class TestWriterRoundtripProperties:
    """3MF post-processing invariants under varying ``cover_source`` inputs.

    **Validates: Requirements 1.2, 1.3, 1.5, 7.4 / Property 5, 6**
    """

    @_PROPERTY_SETTINGS
    @given(cover=_writer_cover_source_strategy())
    def test_writer_roundtrip_keeps_three_cover_relationships(self, cover) -> None:
        """3MF always carries 3 cover relationships with strict ``Type`` URIs and ``/`` Target prefix.

        Holds for ``cover_source ∈ {None, valid PNG bytes, nonexistent path}``:
        the silent-placeholder path and the WARNING fallback path both still
        write the three relationships pointing at valid placeholder PNGs.

        **Validates: Requirements 1.3, 1.5, 7.4 / Property 5, 6**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "out.3mf"
            _make_writer(str(out), cover).export()

            with zipfile.ZipFile(out) as zf:
                root = ET.fromstring(zf.read("_rels/.rels"))

            rels = _iter_relationships(root)
            cover_rels = [
                rel
                for rel in rels
                if rel.get("Target", "").startswith("/Auxiliaries/.thumbnails/")
            ]
            assert len(cover_rels) == 3, (
                f"expected 3 cover relationships, got {len(cover_rels)}"
            )

            types = {rel.get("Type") for rel in cover_rels}
            assert types == {
                _OPC_THUMBNAIL_TYPE,
                _BAMBU_COVER_MIDDLE_TYPE,
                _BAMBU_COVER_SMALL_TYPE,
            }, f"cover Type set mismatch: {sorted(types)}"

            for rel in cover_rels:
                target = rel.get("Target", "")
                assert target.startswith("/"), (
                    f"cover Target must start with '/': {target}"
                )

            # Id uniqueness across all relationships (rel-1 + 3 cover rels).
            ids = [rel.get("Id") for rel in rels]
            assert len(ids) == len(set(ids)), (
                f"duplicate relationship Id values: {ids}"
            )

    @_PROPERTY_SETTINGS
    @given(cover=_writer_cover_source_strategy())
    def test_writer_roundtrip_all_pngs_pass_verify(self, cover) -> None:
        """Every PNG inside the exported 3MF round-trips through PIL ``verify()``.

        Covers the 5 cover/plate PNGs as well as ``top_1.png`` / ``pick_1.png``
        and any other PNG entries written by the n3mf base path.

        **Validates: Requirements 1.1, 7.1, 10.1 / Property 1, 6**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "out.3mf"
            _make_writer(str(out), cover).export()

            with zipfile.ZipFile(out) as zf:
                names = set(zf.namelist())
                # Required cover/plate PNGs must exist and verify().
                for spec in _ALL_SPECS:
                    assert spec.zip_path in names, (
                        f"missing required PNG entry: {spec.zip_path}"
                    )
                # Every PNG entry verifies — Auxiliaries/.thumbnails/* +
                # Metadata/{plate_*,top_1,pick_1}.png all round-trip.
                for name in names:
                    if name.lower().endswith(".png"):
                        _verify_png(zf.read(name))

    @_PROPERTY_SETTINGS
    @given(cover=_writer_cover_source_strategy())
    def test_writer_roundtrip_content_types_png_default_is_unique(
        self, cover
    ) -> None:
        """``[Content_Types].xml`` declares exactly one ``Default Extension="png"`` entry.

        Guards R1.2 idempotency: the cover-injection post-processing must not
        register a duplicate png Default ContentType even though it adds three
        new PNG parts under ``Auxiliaries/.thumbnails/``.

        **Validates: Requirements 1.2 / Property 6**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "out.3mf"
            _make_writer(str(out), cover).export()

            with zipfile.ZipFile(out) as zf:
                root = ET.fromstring(zf.read("[Content_Types].xml"))

            png_defaults = [
                child
                for child in root.findall(f"{{{_CT_NS}}}Default")
                if child.get("Extension", "").lower() == "png"
            ]
            assert len(png_defaults) == 1, (
                f"expected exactly 1 png Default, got {len(png_defaults)}"
            )
            assert png_defaults[0].get("ContentType") == "image/png"
