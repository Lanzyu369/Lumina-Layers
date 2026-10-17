"""Regression tests for accepted raster formats at the native vectorizer handoff.
原生矢量化输入交接的已接受栅格格式回归测试。

WebP and TIFF uploads are accepted by the backend but the native loader cannot
decode them, so they used to fail with a generic 500. These tests drive the
real ``neroued_vectorizer`` and require WebP/TIFF results to match the result
for the same pixels encoded as PNG, with all temp files cleaned up.
"""

from __future__ import annotations

import io
import os
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

nv = pytest.importorskip("neroued_vectorizer")


@pytest.fixture()
def temp_dir(tmp_path, monkeypatch):
    """Isolate config.TEMP_DIR so leftovers can be counted exactly."""
    import config

    work = tmp_path / "temp"
    work.mkdir()
    monkeypatch.setattr(config, "TEMP_DIR", str(work))
    return work


def _banded_rgb() -> Image.Image:
    """Non-square image with four colour bands (stored orientation matters)."""
    img = Image.new("RGB", (96, 64), (255, 255, 255))
    img.paste((220, 20, 60), (0, 16, 96, 32))
    img.paste((255, 230, 0), (0, 32, 96, 48))
    img.paste((0, 102, 255), (48, 48, 96, 64))
    return img


def _rgba_with_transparency() -> Image.Image:
    img = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (16, 16, 64, 64))
    img.paste((0, 0, 255, 255), (32, 32, 48, 48))
    return img


def _write(img: Image.Image, path, fmt: str, **kwargs) -> str:
    img.save(path, fmt, **kwargs)
    return str(path)


def _vectorize(src: str, temp_dir) -> tuple[dict, str]:
    """Run worker_vectorize on a temp copy (the worker deletes its input)."""
    from api.workers.vectorizer_workers import worker_vectorize

    upload = temp_dir / ("upload_" + os.path.basename(src))
    shutil.copyfile(src, upload)
    result = worker_vectorize(str(upload), {})
    with open(result["svg_path"], encoding="utf-8") as f:
        svg = f.read()
    os.unlink(result["svg_path"])
    return result, svg


def _summary(result: dict) -> dict:
    return {k: result[k] for k in ("width", "height", "num_shapes", "num_colors", "palette")}


@pytest.mark.parametrize(
    ("name", "fmt", "kwargs"),
    [
        ("img.webp", "WEBP", {"lossless": True}),
        ("webp_bytes.png", "WEBP", {"lossless": True}),
        ("img.tiff", "TIFF", {}),
        ("img.tif", "TIFF", {"compression": "tiff_lzw"}),
    ],
)
def test_webp_and_tiff_match_png_result(tmp_path, temp_dir, name, fmt, kwargs):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    img = _banded_rgb()
    png = _write(img, src_dir / "ref.png", "PNG")
    other = _write(img, src_dir / name, fmt, **kwargs)

    png_result, png_svg = _vectorize(png, temp_dir)
    result, svg = _vectorize(other, temp_dir)

    assert _summary(result) == _summary(png_result)
    assert (result["width"], result["height"]) == (96, 64)
    assert svg == png_svg
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("fmt", "kwargs"),
    [("WEBP", {"lossless": True, "exact": True}), ("TIFF", {})],
)
def test_alpha_is_preserved_like_png(tmp_path, temp_dir, fmt, kwargs):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    img = _rgba_with_transparency()
    png = _write(img, src_dir / "ref.png", "PNG")
    other = _write(img, src_dir / ("img." + fmt.lower()), fmt, **kwargs)

    png_result, png_svg = _vectorize(png, temp_dir)
    result, svg = _vectorize(other, temp_dir)

    assert _summary(result) == _summary(png_result)
    assert svg == png_svg


def test_handoff_png_keeps_decoded_pixels_and_alpha(tmp_path, temp_dir):
    from api.workers.vectorizer_workers import _transcode_for_native_loader

    img = _rgba_with_transparency()
    src = _write(img, tmp_path / "img.webp", "WEBP", lossless=True, exact=True)

    png_path = _transcode_for_native_loader(src, str(temp_dir))
    try:
        with Image.open(png_path) as out:
            assert out.format == "PNG"
            assert out.mode == "RGBA"
            assert out.tobytes() == img.tobytes()
    finally:
        os.unlink(png_path)


def _orientation6_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = 6  # display rotated 90 degrees clockwise
    return exif


def test_webp_exif_orientation_matches_stored_pixel_png_oracle(tmp_path, temp_dir):
    """WebP EXIF orientation is not applied, like native PNG/JPEG handling."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    img = _banded_rgb()
    png = _write(img, src_dir / "ref.png", "PNG")
    jpeg = _write(img, src_dir / "ref.jpg", "JPEG", quality=95, exif=_orientation6_exif())
    webp = _write(img, src_dir / "img.webp", "WEBP", lossless=True, exif=_orientation6_exif())

    png_result, png_svg = _vectorize(png, temp_dir)
    jpeg_result, _ = _vectorize(jpeg, temp_dir)
    result, svg = _vectorize(webp, temp_dir)

    assert (jpeg_result["width"], jpeg_result["height"]) == (96, 64)
    assert _summary(result) == _summary(png_result)
    assert svg == png_svg


def test_tiff_orientation_tag_matches_decoded_pixel_png_oracle(tmp_path, temp_dir):
    """TIFF Orientation is applied by the decoder; the oracle is the rotated PNG."""
    from api.workers.vectorizer_workers import _transcode_for_native_loader

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    img = _banded_rgb()
    displayed = img.transpose(Image.Transpose.ROTATE_270)
    oracle_png = _write(displayed, src_dir / "oracle.png", "PNG")
    tiff = _write(img, src_dir / "img.tiff", "TIFF", exif=_orientation6_exif())

    png_path = _transcode_for_native_loader(tiff, str(temp_dir))
    try:
        with Image.open(png_path) as out:
            assert out.size == (64, 96)
            assert out.tobytes() == displayed.tobytes()
    finally:
        os.unlink(png_path)

    oracle_result, oracle_svg = _vectorize(oracle_png, temp_dir)
    result, svg = _vectorize(tiff, temp_dir)

    assert (result["width"], result["height"]) == (64, 96)
    assert _summary(result) == _summary(oracle_result)
    assert svg == oracle_svg


@pytest.mark.parametrize(
    ("name", "fmt"),
    [("img.png", "PNG"), ("img.jpg", "JPEG"), ("img.bmp", "BMP")],
)
def test_pillow_pixel_guard_does_not_gate_native_formats(temp_dir, monkeypatch, name, fmt):
    """Native-readable uploads never reach Pillow, so its pixel limit cannot reject them."""
    from api.workers.vectorizer_workers import worker_vectorize

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 200)
    upload = _write(_banded_rgb(), temp_dir / name, fmt)

    result = worker_vectorize(upload, {})

    assert (result["width"], result["height"]) == (96, 64)
    assert Image.MAX_IMAGE_PIXELS == 200
    os.unlink(result["svg_path"])
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "fmt", "kwargs"),
    [("img.webp", "WEBP", {"lossless": True}), ("img.tiff", "TIFF", {})],
)
def test_pillow_pixel_guard_on_webp_tiff_keeps_baseline_failure(
    temp_dir, monkeypatch, name, fmt, kwargs
):
    """Over-limit WebP/TIFF is not decoded; the native loader fails as before."""
    from api.routers.vectorizer import _VECTORIZER_BOUNDARY_ERRORS
    from api.workers.vectorizer_workers import worker_vectorize

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 200)
    upload = _write(_banded_rgb(), temp_dir / name, fmt, **kwargs)
    seen: list[str] = []
    real_vectorize = nv.vectorize

    def _spy(path, config):
        seen.append(path)
        return real_vectorize(path, config)

    with patch.object(nv, "vectorize", side_effect=_spy):
        with pytest.raises(_VECTORIZER_BOUNDARY_ERRORS):
            worker_vectorize(upload, {})

    assert seen == [upload]
    assert Image.MAX_IMAGE_PIXELS == 200
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "fmt"),
    [("img.png", "PNG"), ("img.jpg", "JPEG"), ("img.bmp", "BMP")],
)
def test_natively_readable_formats_keep_original_path(tmp_path, temp_dir, name, fmt):
    from api.workers.vectorizer_workers import worker_vectorize

    upload = _write(_banded_rgb(), temp_dir / name, fmt)
    seen: list[str] = []
    real_vectorize = nv.vectorize

    def _spy(path, config):
        seen.append(path)
        return real_vectorize(path, config)

    with patch.object(nv, "vectorize", side_effect=_spy):
        result = worker_vectorize(upload, {})

    assert seen == [upload]
    os.unlink(result["svg_path"])
    assert list(temp_dir.iterdir()) == []


def test_native_failure_cleans_input_and_handoff_png(tmp_path, temp_dir):
    from api.workers.vectorizer_workers import worker_vectorize

    upload = _write(_banded_rgb(), temp_dir / "img.webp", "WEBP", lossless=True)
    seen: list[str] = []

    def _fail(path, config):
        seen.append(path)
        assert os.path.exists(path)
        raise RuntimeError("native failure")

    with patch.object(nv, "vectorize", side_effect=_fail):
        with pytest.raises(RuntimeError, match="native failure"):
            worker_vectorize(upload, {})

    assert len(seen) == 1 and seen[0] != upload and seen[0].endswith(".png")
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize("keep", [12, 40, -20])
def test_undecodable_webp_still_fails_inside_boundary_and_cleans_up(temp_dir, keep):
    """Broken WebP keeps the existing worker-error policy (mapped to 500)."""
    from api.routers.vectorizer import _VECTORIZER_BOUNDARY_ERRORS
    from api.workers.vectorizer_workers import worker_vectorize

    buf = io.BytesIO()
    _banded_rgb().save(buf, "WEBP", lossless=True)
    upload = temp_dir / "truncated.webp"
    upload.write_bytes(buf.getvalue()[:keep])

    with pytest.raises(_VECTORIZER_BOUNDARY_ERRORS):
        worker_vectorize(str(upload), {})

    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("filename", "fmt", "content_type"),
    [
        ("input.webp", "WEBP", "image/webp"),
        ("input.tiff", "TIFF", "image/tiff"),
        ("webp_bytes.png", "WEBP", "image/png"),
    ],
)
def test_api_vectorize_returns_same_svg_as_png(temp_dir, filename, fmt, content_type):
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.dependencies import get_file_registry, get_worker_pool
    from api.file_registry import FileRegistry
    from api.workers.vectorizer_workers import worker_vectorize

    async def _run_inline(fn, *args):
        return fn(*args)

    def _encode(img_fmt: str) -> bytes:
        buf = io.BytesIO()
        kwargs = {"lossless": True} if img_fmt == "WEBP" else {}
        _banded_rgb().save(buf, img_fmt, **kwargs)
        return buf.getvalue()

    app = create_app()
    registry = FileRegistry()
    pool = SimpleNamespace(submit=AsyncMock(side_effect=_run_inline))
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    client = TestClient(app)
    try:
        bodies = {}
        svgs = {}
        for key, name, img_fmt, ctype in (
            ("png", "input.png", "PNG", "image/png"),
            ("other", filename, fmt, content_type),
        ):
            response = client.post(
                "/api/vectorize",
                files={"image": (name, _encode(img_fmt), ctype)},
                data={"params": "{}"},
            )
            assert response.status_code == 200, response.text
            bodies[key] = response.json()
            download = client.get(bodies[key]["svg_url"])
            assert download.status_code == 200
            svgs[key] = download.text
    finally:
        app.dependency_overrides.clear()

    assert pool.submit.await_args_list[1].args[0] is worker_vectorize
    for field in ("width", "height", "num_shapes", "num_colors", "palette"):
        assert bodies["other"][field] == bodies["png"][field]
    assert svgs["other"] == svgs["png"]
    assert svgs["other"].lstrip().startswith(("<?xml", "<svg"))
    assert 'data-lumina-origin="image-vectorizer"' in svgs["other"]
    leftovers = {p.suffix for p in temp_dir.iterdir()}
    assert leftovers <= {".svg"}
    assert len(list(temp_dir.iterdir())) == 2  # the two registered outputs
