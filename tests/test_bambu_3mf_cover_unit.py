"""Unit tests for ``utils.bambu_3mf_cover``.

中文标题：3MF 封面缩略图模块单元测试

测试覆盖（呼应 task 1 验收点）：

- 5 档目标尺寸（240×180 / 680×510 / 251×188 / 512×512 / 512×512）严格匹配 spec；
- RGBA 半透明图像合成到不透明纯白底，alpha 不会泄漏到输出；
- 占位 PNG 通过 ``PIL.Image.open(...).verify()``；
- letterbox 不裁切（缩放后保留宽高比），剩余区域 RGB 等于 (255, 255, 255)；
- 错误分类映射覆盖六类 ``error_type``，``cover_source is None`` 静默占位。

呼应 Requirements 1.1, 2.1, 2.4, 2.5, 2.6, 2.7, 2.8, 6.1, 8.4 / Property 1, 5, 7。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from utils.bambu_3mf_cover import (
    COVER_PLATE_SPECS,
    COVER_THUMBNAIL_SPECS,
    CoverPngBundle,
    CoverSpec,
    CoverThumbnailBuilder,
)
from utils import bambu_3mf_cover as cover_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_ALL_SPECS = COVER_THUMBNAIL_SPECS + COVER_PLATE_SPECS


def _decode_png(data: bytes) -> Image.Image:
    """Decode PNG bytes into a fully-loaded Pillow image."""
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def _verify_png(data: bytes) -> None:
    """Run ``PIL.Image.open(...).verify()`` and raise on failure."""
    Image.open(io.BytesIO(data)).verify()


def _bundle_field(bundle: CoverPngBundle, spec: CoverSpec) -> bytes:
    """Map a CoverSpec to its corresponding bytes field on the bundle."""
    return {
        "package": bundle.thumbnail_3mf,
        "middle": bundle.thumbnail_middle,
        "small": bundle.thumbnail_small,
        "plate": bundle.plate_main,
        "plate_no_light": bundle.plate_no_light,
    }[spec.logical_name]


# ---------------------------------------------------------------------------
# Module-level constants and dataclasses
# ---------------------------------------------------------------------------


class TestCoverSpecConstants:
    """Lock spec constants against design.md and the reference 3MF sample."""

    def test_thumbnail_specs_have_three_entries(self) -> None:
        assert len(COVER_THUMBNAIL_SPECS) == 3

    def test_plate_specs_have_two_entries(self) -> None:
        assert len(COVER_PLATE_SPECS) == 2

    def test_thumbnail_spec_dimensions_match_design(self) -> None:
        sizes = [(s.logical_name, s.width, s.height) for s in COVER_THUMBNAIL_SPECS]
        assert sizes == [
            ("package", 240, 180),
            ("middle", 680, 510),
            ("small", 251, 188),
        ]

    def test_plate_spec_dimensions_are_512_square(self) -> None:
        for spec in COVER_PLATE_SPECS:
            assert (spec.width, spec.height) == (512, 512)
            assert spec.relationship_type is None

    def test_thumbnail_spec_zip_paths_match_reference_sample(self) -> None:
        # Paths must match `元数据分析/ferris+wheel+electric3.3mf` exactly,
        # including the `.thumbnails` directory casing.
        zip_paths = [s.zip_path for s in COVER_THUMBNAIL_SPECS]
        assert zip_paths == [
            "Auxiliaries/.thumbnails/thumbnail_3mf.png",
            "Auxiliaries/.thumbnails/thumbnail_middle.png",
            "Auxiliaries/.thumbnails/thumbnail_small.png",
        ]

    def test_thumbnail_spec_relationship_types_match_glossary(self) -> None:
        rel_types = [s.relationship_type for s in COVER_THUMBNAIL_SPECS]
        assert rel_types == [
            (
                "http://schemas.openxmlformats.org/package/2006/"
                "relationships/metadata/thumbnail"
            ),
            "http://schemas.bambulab.com/package/2021/cover-thumbnail-middle",
            "http://schemas.bambulab.com/package/2021/cover-thumbnail-small",
        ]

    def test_plate_spec_zip_paths_match_design(self) -> None:
        zip_paths = [s.zip_path for s in COVER_PLATE_SPECS]
        assert zip_paths == [
            "Metadata/plate_1.png",
            "Metadata/plate_no_light_1.png",
        ]

    def test_cover_spec_is_frozen(self) -> None:
        spec = COVER_THUMBNAIL_SPECS[0]
        with pytest.raises((AttributeError, Exception)):
            spec.width = 999  # type: ignore[misc]


class TestCoverPngBundleShape:
    """Bundle dataclass fields are immutable bytes + warning metadata."""

    def test_bundle_is_frozen(self) -> None:
        bundle = CoverThumbnailBuilder().build(None)
        with pytest.raises((AttributeError, Exception)):
            bundle.is_placeholder = False  # type: ignore[misc]

    def test_bundle_fields_are_bytes(self) -> None:
        bundle = CoverThumbnailBuilder().build(None)
        for field_name in (
            "thumbnail_3mf",
            "thumbnail_middle",
            "thumbnail_small",
            "plate_main",
            "plate_no_light",
        ):
            assert isinstance(getattr(bundle, field_name), bytes)


# ---------------------------------------------------------------------------
# Successful build path
# ---------------------------------------------------------------------------


class TestSuccessfulBuild:
    """End-to-end: an opaque RGB image yields five real PNGs at the right sizes."""

    @pytest.fixture
    def red_rgb_image(self) -> Image.Image:
        return Image.new("RGB", (100, 100), (200, 30, 40))

    def test_build_returns_real_bundle_for_rgb_input(
        self, red_rgb_image: Image.Image
    ) -> None:
        bundle = CoverThumbnailBuilder().build(red_rgb_image)
        assert bundle.is_placeholder is False
        assert bundle.warning is None

    @pytest.mark.parametrize(
        "spec",
        _ALL_SPECS,
        ids=[s.logical_name for s in _ALL_SPECS],
    )
    def test_each_field_decodes_to_exact_target_size_and_rgb_mode(
        self, red_rgb_image: Image.Image, spec: CoverSpec
    ) -> None:
        bundle = CoverThumbnailBuilder().build(red_rgb_image)
        decoded = _decode_png(_bundle_field(bundle, spec))
        assert decoded.size == (spec.width, spec.height)
        assert decoded.mode == "RGB"

    @pytest.mark.parametrize(
        "spec",
        _ALL_SPECS,
        ids=[s.logical_name for s in _ALL_SPECS],
    )
    def test_each_field_passes_pil_verify(
        self, red_rgb_image: Image.Image, spec: CoverSpec
    ) -> None:
        bundle = CoverThumbnailBuilder().build(red_rgb_image)
        _verify_png(_bundle_field(bundle, spec))

    def test_plate_main_and_plate_no_light_are_byte_equal_for_same_source(
        self, red_rgb_image: Image.Image
    ) -> None:
        # Both plate specs are 512×512 with the same letterbox parameters; the
        # two outputs must be byte-identical for the same source (R8.4 implies
        # this because the source is decoded once and `_letterbox_fit` is
        # deterministic).
        bundle = CoverThumbnailBuilder().build(red_rgb_image)
        assert bundle.plate_main == bundle.plate_no_light

    def test_build_decodes_source_only_once(
        self, red_rgb_image: Image.Image, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Property 9 (decoded once, encoded five times). Wraps the module-level
        # helpers via monkeypatch to count invocations.
        decode_calls = []
        original_decode = cover_module._decode_source

        def counting_decode(source):
            decode_calls.append(source)
            return original_decode(source)

        monkeypatch.setattr(cover_module, "_decode_source", counting_decode)
        CoverThumbnailBuilder().build(red_rgb_image)
        assert len(decode_calls) == 1

    def test_build_calls_letterbox_and_encode_five_times_each(
        self, red_rgb_image: Image.Image, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        encode_calls: list = []
        letterbox_calls: list = []
        original_letterbox = cover_module._letterbox_fit
        original_encode = cover_module._encode_png

        def counting_letterbox(image, target):
            letterbox_calls.append(target)
            return original_letterbox(image, target)

        def counting_encode(image):
            encode_calls.append(image.size)
            return original_encode(image)

        monkeypatch.setattr(cover_module, "_letterbox_fit", counting_letterbox)
        monkeypatch.setattr(cover_module, "_encode_png", counting_encode)

        CoverThumbnailBuilder().build(red_rgb_image)
        assert len(letterbox_calls) == 5
        assert len(encode_calls) == 5
        assert set(letterbox_calls) == {
            (240, 180),
            (680, 510),
            (251, 188),
            (512, 512),
        }


# ---------------------------------------------------------------------------
# Letterbox semantics
# ---------------------------------------------------------------------------


class TestLetterboxFit:
    """Direct tests on ``_letterbox_fit`` covering R2.4/R2.5/R2.6/R2.7."""

    def test_letterbox_returns_target_size_rgb_mode(self) -> None:
        src = Image.new("RGB", (100, 100), (10, 20, 30))
        out = cover_module._letterbox_fit(src, (240, 180))
        assert out.size == (240, 180)
        assert out.mode == "RGB"

    def test_letterbox_does_not_crop_wide_source(self) -> None:
        # Source 200×50 (4:1) into 100×100 — height becomes 25, width 100.
        # Pixels along the horizontal stripe should match source color, top
        # and bottom borders should be opaque white.
        src = Image.new("RGB", (200, 50), (10, 200, 50))
        out = cover_module._letterbox_fit(src, (100, 100))

        # Top-left corner is in the white letterbox area (since target h=100
        # but scaled image only covers rows ~37..62).
        assert out.getpixel((0, 0)) == (255, 255, 255)
        assert out.getpixel((99, 0)) == (255, 255, 255)
        assert out.getpixel((0, 99)) == (255, 255, 255)
        assert out.getpixel((99, 99)) == (255, 255, 255)

        # Center pixel falls inside the source content area.
        center = out.getpixel((50, 50))
        # LANCZOS is exact on a uniform-color rectangle.
        assert center == (10, 200, 50)

    def test_letterbox_does_not_crop_tall_source(self) -> None:
        src = Image.new("RGB", (50, 200), (200, 30, 40))
        out = cover_module._letterbox_fit(src, (100, 100))
        # Left and right vertical strips should be white letterbox.
        assert out.getpixel((0, 50)) == (255, 255, 255)
        assert out.getpixel((99, 50)) == (255, 255, 255)
        # Center column is content.
        assert out.getpixel((50, 50)) == (200, 30, 40)

    def test_letterbox_preserves_uniform_color_for_same_aspect_ratio(self) -> None:
        # Square source into square target: no letterbox bands.
        src = Image.new("RGB", (200, 200), (123, 200, 50))
        out = cover_module._letterbox_fit(src, (100, 100))
        # Sample interior pixels far from edges; LANCZOS resampling on a
        # uniform color preserves the exact color in the interior.
        assert out.getpixel((50, 50)) == (123, 200, 50)
        assert out.getpixel((10, 10)) == (123, 200, 50)


class TestRgbaCompositeToWhite:
    """RGBA / half-transparent input must composite to opaque white."""

    def test_fully_transparent_rgba_yields_pure_white_output(self) -> None:
        # 100×100 image with alpha=0 everywhere. After compositing, every
        # pixel of the letterboxed output should be (255, 255, 255).
        src = Image.new("RGBA", (100, 100), (0, 200, 50, 0))
        bundle = CoverThumbnailBuilder().build(src)
        decoded = _decode_png(bundle.thumbnail_3mf)
        # Sample interior pixels — borders are white via letterbox, interior
        # must also be white because the original was fully transparent.
        for x, y in [(120, 90), (60, 90), (200, 90), (120, 30), (120, 150)]:
            if 0 <= x < decoded.width and 0 <= y < decoded.height:
                assert decoded.getpixel((x, y)) == (255, 255, 255)

    def test_half_transparent_rgba_blends_toward_white(self) -> None:
        # Source: 100×100 image, fully covered by green at alpha=128. After
        # compositing onto opaque white the interior should be roughly halfway
        # between (0, 200, 50) and (255, 255, 255), i.e. ≈ (128, 228, 153).
        src = Image.new("RGBA", (100, 100), (0, 200, 50, 128))
        bundle = CoverThumbnailBuilder().build(src)
        decoded = _decode_png(bundle.thumbnail_3mf)
        # Center pixel is inside the scaled content area.
        cx, cy = decoded.width // 2, decoded.height // 2
        r, g, b = decoded.getpixel((cx, cy))
        # Tolerance covers PNG quantization + LANCZOS resampling.
        assert 110 <= r <= 145, f"r={r} not in [110,145]"
        assert 215 <= g <= 240, f"g={g} not in [215,240]"
        assert 140 <= b <= 170, f"b={b} not in [140,170]"

    def test_rgba_path_outputs_rgb_mode_no_alpha(self) -> None:
        src = Image.new("RGBA", (100, 100), (10, 20, 30, 200))
        bundle = CoverThumbnailBuilder().build(src)
        for spec in _ALL_SPECS:
            decoded = _decode_png(_bundle_field(bundle, spec))
            assert decoded.mode == "RGB"


# ---------------------------------------------------------------------------
# Placeholder paths and error classification
# ---------------------------------------------------------------------------


class TestSilentPlaceholder:
    """``cover_source is None`` is the silent calibration / kit path."""

    def test_none_source_returns_placeholder_without_warning(self) -> None:
        bundle = CoverThumbnailBuilder().build(None)
        assert bundle.is_placeholder is True
        assert bundle.warning is None

    def test_placeholder_pngs_pass_pil_verify(self) -> None:
        bundle = CoverThumbnailBuilder().build(None)
        for spec in _ALL_SPECS:
            _verify_png(_bundle_field(bundle, spec))

    def test_placeholder_pngs_have_correct_sizes_and_rgb_mode(self) -> None:
        bundle = CoverThumbnailBuilder().build(None)
        for spec in _ALL_SPECS:
            decoded = _decode_png(_bundle_field(bundle, spec))
            assert decoded.size == (spec.width, spec.height)
            assert decoded.mode == "RGB"

    def test_placeholder_pngs_are_pure_white(self) -> None:
        bundle = CoverThumbnailBuilder().build(None)
        for spec in _ALL_SPECS:
            decoded = _decode_png(_bundle_field(bundle, spec))
            assert decoded.getpixel((decoded.width // 2, decoded.height // 2)) == (
                255,
                255,
                255,
            )

    def test_placeholder_cache_is_reused_across_builds(self) -> None:
        # Process-lifetime cache: same bytes object identity for the same size.
        b1 = CoverThumbnailBuilder().build(None)
        b2 = CoverThumbnailBuilder().build(None)
        assert b1.thumbnail_3mf is b2.thumbnail_3mf
        assert b1.plate_main is b2.plate_main


class TestErrorClassification:
    """``error_type`` mapping covers the six documented categories."""

    def test_string_path_not_existing_yields_source_unavailable(
        self, tmp_path: Path
    ) -> None:
        bundle = CoverThumbnailBuilder().build(str(tmp_path / "no_such.png"))
        assert bundle.is_placeholder is True
        assert bundle.warning is not None
        assert bundle.warning["error_type"] == "source_unavailable"
        assert bundle.warning["fallback_action"] == "placeholder_written"

    def test_zero_byte_file_yields_source_empty(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.png"
        empty.write_bytes(b"")
        bundle = CoverThumbnailBuilder().build(str(empty))
        assert bundle.warning is not None
        assert bundle.warning["error_type"] == "source_empty"

    def test_empty_bytes_yields_source_empty(self) -> None:
        bundle = CoverThumbnailBuilder().build(b"")
        assert bundle.warning is not None
        assert bundle.warning["error_type"] == "source_empty"

    def test_corrupt_bytes_yield_source_decode_error(self) -> None:
        bundle = CoverThumbnailBuilder().build(b"not a png at all")
        assert bundle.warning is not None
        assert bundle.warning["error_type"] == "source_decode_error"

    def test_corrupt_file_yields_source_decode_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not really a png file")
        bundle = CoverThumbnailBuilder().build(str(bad))
        assert bundle.warning is not None
        assert bundle.warning["error_type"] == "source_decode_error"

    def test_unsupported_type_yields_source_unsupported_type(self) -> None:
        bundle = CoverThumbnailBuilder().build(12345)  # type: ignore[arg-type]
        assert bundle.warning is not None
        assert bundle.warning["error_type"] == "source_unsupported_type"

    def test_valid_path_returns_real_bundle(self, tmp_path: Path) -> None:
        path = tmp_path / "good.png"
        Image.new("RGB", (100, 100), (10, 200, 50)).save(path, format="PNG")
        bundle = CoverThumbnailBuilder().build(str(path))
        assert bundle.is_placeholder is False
        assert bundle.warning is None

    def test_valid_bytes_returns_real_bundle(self) -> None:
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), (10, 200, 50)).save(buf, format="PNG")
        bundle = CoverThumbnailBuilder().build(buf.getvalue())
        assert bundle.is_placeholder is False
        assert bundle.warning is None

    def test_warning_dict_contains_required_fields(self) -> None:
        bundle = CoverThumbnailBuilder().build(b"")
        assert bundle.warning is not None
        assert set(bundle.warning.keys()) >= {
            "error_type",
            "error_message",
            "fallback_action",
        }
        assert bundle.warning["fallback_action"] == "placeholder_written"

    def test_warning_field_lengths_are_truncated(self) -> None:
        # Build a synthetic warning via the public path: feed a deeply nested
        # bad bytes blob. We cannot directly exercise the truncation through
        # the natural decode path easily, so we call the helper directly.
        truncated = cover_module._truncate("x" * 5000, 2048)
        assert len(truncated) <= 2048
        assert truncated.endswith("...")

    def test_truncate_short_value_is_unchanged(self) -> None:
        assert cover_module._truncate("short", 2048) == "short"


class TestEncodeFailureFallback:
    """If ``_encode_png`` raises mid-build, the whole bundle is placeholder."""

    def test_encode_failure_downgrades_to_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(image):
            raise RuntimeError("synthetic encode failure")

        monkeypatch.setattr(cover_module, "_encode_png", boom)
        bundle = CoverThumbnailBuilder().build(Image.new("RGB", (100, 100), 0))
        # Encode failure should map to cover_encode_error and a placeholder
        # bundle. Since _encode_png is also used by the placeholder helper,
        # the placeholder bundle will rely on the cache populated during
        # earlier tests; if the cache is empty in this isolated test run we
        # still expect the build to fall back without raising.
        assert bundle.is_placeholder is True
        assert bundle.warning is not None
        assert bundle.warning["error_type"] == "cover_encode_error"
        assert bundle.warning["fallback_action"] == "placeholder_written"


class TestMemoryFailurePropagation:
    """Allocator failures must stop export instead of entering placeholders."""

    def test_decode_memory_error_is_not_downgraded(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            cover_module,
            "_composite_to_white",
            lambda _image: (_ for _ in ()).throw(
                MemoryError("cover decode allocation failed")
            ),
        )

        with pytest.raises(MemoryError, match="cover decode allocation failed"):
            CoverThumbnailBuilder().build(Image.new("RGB", (100, 100), 0))

    def test_encode_memory_error_is_not_downgraded(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            cover_module,
            "_encode_png",
            lambda _image: (_ for _ in ()).throw(
                MemoryError("cover encode allocation failed")
            ),
        )

        with pytest.raises(MemoryError, match="cover encode allocation failed"):
            CoverThumbnailBuilder().build(Image.new("RGB", (100, 100), 0))

    def test_png_verify_memory_error_is_not_wrapped(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            cover_module.Image,
            "open",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                MemoryError("cover verify allocation failed")
            ),
        )

        with pytest.raises(MemoryError, match="cover verify allocation failed"):
            cover_module._encode_png(Image.new("RGB", (8, 8), 0))


# ---------------------------------------------------------------------------
# RGB-mode invariant on output PNGs
# ---------------------------------------------------------------------------


class TestEncodedPngsAreRgbWithoutAlpha:
    """Every encoded PNG must decode to mode ``"RGB"`` (R2.6 — no alpha)."""

    def test_rgb_source_rgb_outputs(self) -> None:
        bundle = CoverThumbnailBuilder().build(Image.new("RGB", (50, 50), 128))
        for spec in _ALL_SPECS:
            decoded = _decode_png(_bundle_field(bundle, spec))
            assert decoded.mode == "RGB"

    def test_rgba_source_rgb_outputs(self) -> None:
        bundle = CoverThumbnailBuilder().build(
            Image.new("RGBA", (50, 50), (10, 20, 30, 200))
        )
        for spec in _ALL_SPECS:
            decoded = _decode_png(_bundle_field(bundle, spec))
            assert decoded.mode == "RGB"

    def test_grayscale_source_rgb_outputs(self) -> None:
        bundle = CoverThumbnailBuilder().build(Image.new("L", (50, 50), 100))
        for spec in _ALL_SPECS:
            decoded = _decode_png(_bundle_field(bundle, spec))
            assert decoded.mode == "RGB"
