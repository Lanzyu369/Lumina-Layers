"""Lumina Studio - 3MF Cover Thumbnail Builder

中文标题：3MF 封面缩略图构建器

This module turns a single cover image source into the five PNG byte payloads
that a Bambu/Orca-style 3MF package needs:

- 三张 OPC + Bambu 私有 cover 缩略图（写入 ``Auxiliaries/.thumbnails/``）
- 两张 512×512 盘内 plate 预览（写入 ``Metadata/plate_*.png``）

公开类型与常量来自 spec ``.kiro/specs/3mf-cover-thumbnail/design.md``，与样本
``元数据分析/ferris+wheel+electric3.3mf`` 中的目录结构与关系类型 URI 完全一致。

设计要点：
- 5 张 PNG 共享同一份解码结果（``_decode_source`` 只跑一次）；
- letterbox 等比缩放 + 居中放置 + 不裁切，剩余区域填充不透明纯白；
- 任何解码 / 编码异常都被捕获为占位 bundle，调用方可以同步检查 ``warning``
  字段决定是否发出 WARNING；``cover_source is None`` 时静默占位。
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Tuple, Union

from PIL import Image


__all__ = [
    "CoverSpec",
    "CoverPngBundle",
    "CoverThumbnailBuilder",
    "COVER_THUMBNAIL_SPECS",
    "COVER_PLATE_SPECS",
    "clear_cover_thumbnail_cache",
]


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverSpec:
    """Single cover or plate PNG specification.

    单档封面 / plate PNG 的规格。

    Attributes:
        logical_name: Debug/log name. Domain values are
            ``{"package", "middle", "small", "plate", "plate_no_light"}``.
            (调试与日志用的逻辑名)
        width: Target width in pixels. (目标宽度，像素)
        height: Target height in pixels. (目标高度，像素)
        zip_path: Path inside the 3MF ZIP package, no leading ``/``. The
            package-level relationship target is ``"/" + zip_path``.
            (在 3MF ZIP 包内的路径，不含开头 ``/``；写关系条目时 ``Target = "/" +
            zip_path``)
        relationship_type: OPC / Bambu relationship type URI written into
            ``_rels/.rels``. ``None`` means the PNG is not exposed via a
            package-level relationship (e.g. plate previews referenced from
            ``Metadata/model_settings.config`` keys).
            (写入 ``_rels/.rels`` 的关系类型 URI；``None`` 表示该 PNG 不通过包级
            关系暴露)
    """

    logical_name: str
    width: int
    height: int
    zip_path: str
    relationship_type: Optional[str]


# Auxiliaries/.thumbnails/* — written into _rels/.rels per design table.
# 顺序与 ``元数据分析/ferris+wheel+electric3.3mf`` 一致。
COVER_THUMBNAIL_SPECS: Tuple[CoverSpec, ...] = (
    CoverSpec(
        logical_name="package",
        width=240,
        height=180,
        zip_path="Auxiliaries/.thumbnails/thumbnail_3mf.png",
        relationship_type=(
            "http://schemas.openxmlformats.org/package/2006/"
            "relationships/metadata/thumbnail"
        ),
    ),
    CoverSpec(
        logical_name="middle",
        width=680,
        height=510,
        zip_path="Auxiliaries/.thumbnails/thumbnail_middle.png",
        relationship_type=(
            "http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"
        ),
    ),
    CoverSpec(
        logical_name="small",
        width=251,
        height=188,
        zip_path="Auxiliaries/.thumbnails/thumbnail_small.png",
        relationship_type=(
            "http://schemas.bambulab.com/package/2021/cover-thumbnail-small"
        ),
    ),
)


# Metadata/plate_*.png — referenced via Metadata/model_settings.config keys.
# 没有包级关系条目，因此 ``relationship_type=None``。
COVER_PLATE_SPECS: Tuple[CoverSpec, ...] = (
    CoverSpec(
        logical_name="plate",
        width=512,
        height=512,
        zip_path="Metadata/plate_1.png",
        relationship_type=None,
    ),
    CoverSpec(
        logical_name="plate_no_light",
        width=512,
        height=512,
        zip_path="Metadata/plate_no_light_1.png",
        relationship_type=None,
    ),
)


@dataclass(frozen=True)
class CoverPngBundle:
    """All cover + plate PNG bytes one 3MF export needs.

    单次 3MF 导出所需的全部 cover + plate PNG 字节集合。

    Attributes:
        thumbnail_3mf: 240×180 OPC standard cover PNG bytes, written to
            ``Auxiliaries/.thumbnails/thumbnail_3mf.png``.
        thumbnail_middle: 680×510 Bambu cover-thumbnail-middle PNG bytes,
            written to ``Auxiliaries/.thumbnails/thumbnail_middle.png``.
        thumbnail_small: 251×188 Bambu cover-thumbnail-small PNG bytes,
            written to ``Auxiliaries/.thumbnails/thumbnail_small.png``.
        plate_main: 512×512 plate preview PNG bytes, written to
            ``Metadata/plate_1.png``.
        plate_no_light: 512×512 plate-no-light preview PNG bytes, written to
            ``Metadata/plate_no_light_1.png``.
        is_placeholder: ``True`` iff all five fields come from the placeholder
            cache (i.e. were not derived from a usable ``cover_source``).
            (是否所有 PNG 均为占位字节)
        warning: When the build fell back to placeholder due to a real failure,
            this dict carries ``error_type`` / ``error_message`` /
            ``fallback_action``. ``None`` when the build succeeded **or** when
            ``cover_source is None`` (silent placeholder for calibration / kit
            paths). The ``path`` field is appended by the writer when emitting
            the WARNING log because only the writer knows ``output_path``.
            (失败回退路径下提供结构化日志字段；``cover_source is None`` 的静默占位
            场景为 ``None``)
    """

    thumbnail_3mf: bytes
    thumbnail_middle: bytes
    thumbnail_small: bytes
    plate_main: bytes
    plate_no_light: bytes
    is_placeholder: bool
    warning: Optional[dict]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# Module-level cache: process-wide white-background placeholder PNG bytes,
# keyed by ``(width, height)``. Each size is encoded at most once per
# interpreter lifetime.
_PLACEHOLDER_PNG_CACHE: dict = {}
_COVER_PATH_BUNDLE_CACHE_SIZE = 64


_ALL_SPECS: Tuple[CoverSpec, ...] = COVER_THUMBNAIL_SPECS + COVER_PLATE_SPECS


# Acceptable cover_source types per design (str path, raw bytes, decoded
# Pillow image, or explicit None for silent placeholder).
_CoverSource = Union[str, bytes, "Image.Image", None]


def _truncate(value: str, limit: int) -> str:
    """Truncate ``value`` to at most ``limit`` characters, ``...`` suffix on cut.

    Mirrors the field-length contract from R6.3 (``error_message`` ≤ 2048,
    ``error_type`` ≤ 256, ``path`` ≤ 1024 chars).
    """

    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def _make_warning(error_type: str, error_message: str) -> dict:
    """Build the ``error_type`` / ``error_message`` / ``fallback_action`` triple.

    ``path`` is intentionally left out — the writer fills it when emitting the
    structured WARNING (``bambu_3mf_cover_thumbnail_failed``) because only the
    writer knows the output 3MF path.
    """

    return {
        "error_type": _truncate(error_type, 256),
        "error_message": _truncate(error_message, 2048),
        "fallback_action": "placeholder_written",
    }


def _composite_to_white(image: "Image.Image") -> "Image.Image":
    """Alpha-composite ``image`` onto opaque white and return an RGB copy.

    支持 RGBA / LA / 含透明色的 P 等模式；对纯 RGB / L 则直接 ``convert("RGB")``。
    """

    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        composited = Image.alpha_composite(white, rgba)
        return composited.convert("RGB")
    return image.convert("RGB")


def _decode_source(
    source: _CoverSource,
) -> Tuple[Optional["Image.Image"], Optional[dict]]:
    """Decode ``source`` into an opaque RGB Pillow image.

    Returns ``(image, None)`` on success, ``(None, None)`` for the silent
    ``source is None`` path, and ``(None, warning_dict)`` for any failure.

    错误分类映射（呼应 design Source Resolution Policy 表）：

    - ``source_unavailable``：``str`` 路径不存在
    - ``source_empty``：``str`` 路径文件 0 字节、或 ``bytes`` 长度为 0
    - ``source_decode_error``：Pillow 解码异常
    - ``source_zero_dimension``：解码后宽或高 < 1
    - ``source_unsupported_type``：``cover_source`` 既不是
      ``None`` / ``str`` / ``bytes`` / ``PIL.Image.Image``
    """

    if source is None:
        return None, None

    if isinstance(source, str):
        try:
            if not os.path.exists(source):
                return None, _make_warning(
                    "source_unavailable", f"no such file: {source}"
                )
            try:
                size = os.path.getsize(source)
            except OSError as exc:
                return None, _make_warning(
                    "source_unavailable", f"stat failed: {exc}"
                )
            if size == 0:
                return None, _make_warning(
                    "source_empty", f"zero-byte file: {source}"
                )
            with Image.open(source) as opened:
                opened.load()
                if opened.width < 1 or opened.height < 1:
                    return None, _make_warning(
                        "source_zero_dimension",
                        f"decoded size {opened.size} has zero dimension",
                    )
                # _composite_to_white internally calls convert(); make a real
                # in-memory copy first so we can release the file handle when
                # the ``with`` block exits.
                return _composite_to_white(opened), None
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            return None, _make_warning("source_decode_error", str(exc))
        except Exception as exc:  # noqa: BLE001 - defensive: any decode failure
            return None, _make_warning("source_decode_error", str(exc))

    if isinstance(source, (bytes, bytearray, memoryview)):
        raw = bytes(source)
        if len(raw) == 0:
            return None, _make_warning("source_empty", "empty bytes")
        try:
            with Image.open(io.BytesIO(raw)) as opened:
                opened.load()
                if opened.width < 1 or opened.height < 1:
                    return None, _make_warning(
                        "source_zero_dimension",
                        f"decoded size {opened.size} has zero dimension",
                    )
                return _composite_to_white(opened), None
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            return None, _make_warning("source_decode_error", str(exc))
        except Exception as exc:  # noqa: BLE001
            return None, _make_warning("source_decode_error", str(exc))

    if isinstance(source, Image.Image):
        try:
            if source.width < 1 or source.height < 1:
                return None, _make_warning(
                    "source_zero_dimension",
                    f"image size {source.size} has zero dimension",
                )
            return _composite_to_white(source), None
        except Exception as exc:  # noqa: BLE001
            return None, _make_warning("source_decode_error", str(exc))

    return None, _make_warning(
        "source_unsupported_type",
        f"unsupported cover_source type: {type(source).__name__}",
    )


def _letterbox_fit(
    image: "Image.Image", target: Tuple[int, int]
) -> "Image.Image":
    """Scale ``image`` uniformly into ``target`` and center on opaque white.

    等比缩放 + 居中放置 + 不裁切；剩余区域填充不透明纯白 ``(255, 255, 255)``，
    返回 RGB 模式的目标尺寸图像。

    Args:
        image: Source Pillow image. ``_decode_source`` already converted to RGB
            with alpha composited to white, so the RGBA branch below is purely
            defensive against future link-up changes.
        target: ``(width, height)`` in pixels.

    Returns:
        A new ``Image.Image`` with mode ``"RGB"`` and size exactly ``target``.
    """

    target_w, target_h = target
    src_w, src_h = image.size

    if src_w < 1 or src_h < 1:
        return Image.new("RGB", target, (255, 255, 255))

    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))

    scaled = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", target, (255, 255, 255))
    offset = ((target_w - new_w) // 2, (target_h - new_h) // 2)

    if scaled.mode == "RGBA":
        # Defensive: _decode_source flattens alpha already. If a future caller
        # hands us RGBA we still composite onto white via paste's mask.
        canvas.paste(scaled, offset, mask=scaled.split()[-1])
    else:
        canvas.paste(scaled if scaled.mode == "RGB" else scaled.convert("RGB"), offset)

    return canvas


def _encode_png(image: "Image.Image") -> bytes:
    """PNG-encode ``image`` (mode ``RGB``) and verify the output round-trips.

    Raises:
        RuntimeError: If the encoded bytes fail ``Image.open(...).verify()``.
            ``CoverThumbnailBuilder.build`` catches this and downgrades the
            whole bundle to placeholder + ``cover_encode_error`` warning.
    """

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    payload = buffer.getvalue()

    try:
        Image.open(io.BytesIO(payload)).verify()
    except Exception as exc:  # noqa: BLE001 - we re-raise as RuntimeError
        raise RuntimeError(f"PNG verify() failed: {exc}") from exc

    return payload


def _get_placeholder_png(width: int, height: int) -> bytes:
    """Return a cached opaque-white PNG of size ``(width, height)``.

    占位 PNG 是 RGB 模式纯白底，与 letterbox 算法剩余区域底色一致；进程生命周期内
    每个尺寸只编码一次。
    """

    key = (width, height)
    cached = _PLACEHOLDER_PNG_CACHE.get(key)
    if cached is not None:
        return cached

    canvas = Image.new("RGB", key, (255, 255, 255))
    payload = _encode_png(canvas)
    _PLACEHOLDER_PNG_CACHE[key] = payload
    return payload


def _build_placeholder_bundle(warning: Optional[dict]) -> CoverPngBundle:
    """Build a ``CoverPngBundle`` whose five fields all come from the cache."""

    return CoverPngBundle(
        thumbnail_3mf=_get_placeholder_png(
            COVER_THUMBNAIL_SPECS[0].width, COVER_THUMBNAIL_SPECS[0].height
        ),
        thumbnail_middle=_get_placeholder_png(
            COVER_THUMBNAIL_SPECS[1].width, COVER_THUMBNAIL_SPECS[1].height
        ),
        thumbnail_small=_get_placeholder_png(
            COVER_THUMBNAIL_SPECS[2].width, COVER_THUMBNAIL_SPECS[2].height
        ),
        plate_main=_get_placeholder_png(
            COVER_PLATE_SPECS[0].width, COVER_PLATE_SPECS[0].height
        ),
        plate_no_light=_get_placeholder_png(
            COVER_PLATE_SPECS[1].width, COVER_PLATE_SPECS[1].height
        ),
        is_placeholder=True,
        warning=warning,
    )


def _clone_cover_bundle(bundle: CoverPngBundle) -> CoverPngBundle:
    """Return a shallow-safe copy of a cached cover bundle."""

    return CoverPngBundle(
        thumbnail_3mf=bundle.thumbnail_3mf,
        thumbnail_middle=bundle.thumbnail_middle,
        thumbnail_small=bundle.thumbnail_small,
        plate_main=bundle.plate_main,
        plate_no_light=bundle.plate_no_light,
        is_placeholder=bundle.is_placeholder,
        warning=dict(bundle.warning) if bundle.warning is not None else None,
    )


def _cover_path_cache_key(
    source: _CoverSource,
) -> tuple[str, int, int] | None:
    """Return a stable cache key for unchanged filesystem cover sources."""

    if not isinstance(source, str):
        return None
    try:
        path_abs = os.path.abspath(source)
        stat = os.stat(path_abs)
    except (TypeError, OSError, ValueError):
        return None
    return (path_abs, int(stat.st_mtime_ns), int(stat.st_size))


@lru_cache(maxsize=_COVER_PATH_BUNDLE_CACHE_SIZE)
def _build_cover_path_bundle_cached(
    path_abs: str,
    _mtime_ns: int,
    _size_bytes: int,
) -> CoverPngBundle:
    """Build and cache cover PNG payloads for an unchanged image path."""

    return _build_cover_bundle_uncached(path_abs)


def clear_cover_thumbnail_cache() -> None:
    """Clear process-local cover thumbnail bundle caches."""

    _build_cover_path_bundle_cached.cache_clear()


def _build_cover_bundle_uncached(source: _CoverSource) -> CoverPngBundle:
    """Decode ``source`` and produce a full ``CoverPngBundle`` without caching."""

    image, decode_warning = _decode_source(source)
    if image is None:
        return _build_placeholder_bundle(decode_warning)

    try:
        return CoverPngBundle(
            thumbnail_3mf=_encode_png(
                _letterbox_fit(
                    image,
                    (
                        COVER_THUMBNAIL_SPECS[0].width,
                        COVER_THUMBNAIL_SPECS[0].height,
                    ),
                )
            ),
            thumbnail_middle=_encode_png(
                _letterbox_fit(
                    image,
                    (
                        COVER_THUMBNAIL_SPECS[1].width,
                        COVER_THUMBNAIL_SPECS[1].height,
                    ),
                )
            ),
            thumbnail_small=_encode_png(
                _letterbox_fit(
                    image,
                    (
                        COVER_THUMBNAIL_SPECS[2].width,
                        COVER_THUMBNAIL_SPECS[2].height,
                    ),
                )
            ),
            plate_main=_encode_png(
                _letterbox_fit(
                    image,
                    (
                        COVER_PLATE_SPECS[0].width,
                        COVER_PLATE_SPECS[0].height,
                    ),
                )
            ),
            plate_no_light=_encode_png(
                _letterbox_fit(
                    image,
                    (
                        COVER_PLATE_SPECS[1].width,
                        COVER_PLATE_SPECS[1].height,
                    ),
                )
            ),
            is_placeholder=False,
            warning=None,
        )
    except Exception as exc:  # noqa: BLE001 - any encode failure → placeholder
        warning = {
            "error_type": _truncate("cover_encode_error", 256),
            "error_message": _truncate(str(exc), 2048),
            "fallback_action": "placeholder_written",
        }
        return _build_placeholder_bundle(warning)


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


class CoverThumbnailBuilder:
    """Convert any cover source into a ``CoverPngBundle``.

    Pure-function builder — no mutable state across ``build()`` calls.
    单次 ``build()`` 内部仅调用一次 ``_decode_source`` + 一次 RGB 合成；之后对 5
    档目标尺寸独立执行 ``_letterbox_fit`` + ``_encode_png``，5 张 PNG 共享同一
    ``Image`` 对象（呼应 R8.4）。
    """

    def build(self, source: _CoverSource) -> CoverPngBundle:
        """Decode ``source`` and produce a full ``CoverPngBundle``.

        Args:
            source:
                ``None`` 表示无源（calibration / 色卡 / 单段 kit / recipe swatch
                等路径），返回全占位 bundle 且 ``warning is None``（静默占位）。
                ``str`` 视为文件路径。
                ``bytes`` 视为已编码图像字节流。
                ``PIL.Image.Image`` 视为已解码图像。
                其他类型映射到 ``source_unsupported_type``。

        Returns:
            CoverPngBundle: 任意解码 / 编码异常都被捕获并转换为
            ``is_placeholder=True`` 且 ``warning != None`` 的占位 bundle，
            异常不向上传播。
        """

        cache_key = _cover_path_cache_key(source)
        if cache_key is not None:
            return _clone_cover_bundle(_build_cover_path_bundle_cached(*cache_key))
        return _build_cover_bundle_uncached(source)
