"""Helpers for private ColorChecker calibration artifacts.
ColorChecker 内部临时产物辅助函数。
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from api.file_registry import FileRegistry

COLORCHECKER_FULL_PENDING_PURPOSE = "colorchecker_full_pending"
COLORCHECKER_FULL_PURPOSE = "colorchecker_full"
COLORCHECKER_SOURCE_PURPOSE = "colorchecker_source"
_COLORCHECKER_FULL_PURPOSES = {
    COLORCHECKER_FULL_PENDING_PURPOSE,
    COLORCHECKER_FULL_PURPOSE,
}
_COLORCHECKER_PRIVATE_PURPOSES = {
    *_COLORCHECKER_FULL_PURPOSES,
    COLORCHECKER_SOURCE_PURPOSE,
}


def resolve_colorchecker_full_path(registry: FileRegistry, file_id: str) -> str:
    """Resolve a private ColorChecker full-image file id to a local path.
    将内部完整校色图 file id 解析为本地路径。
    """
    if not file_id:
        raise HTTPException(status_code=422, detail="ColorChecker file id is required")
    entry = registry.get_entry(file_id)
    if (
        entry is None
        or entry.get("purpose") != COLORCHECKER_FULL_PURPOSE
        or entry.get("is_public") is not False
    ):
        raise HTTPException(status_code=404, detail="ColorChecker calibrated image not found or expired")
    result = registry.resolve(file_id)
    if result is None:
        raise HTTPException(status_code=404, detail="ColorChecker calibrated image not found or expired")
    path, _filename = result
    return path


def load_colorchecker_full_rgb(registry: FileRegistry, file_id: str) -> np.ndarray:
    """Load a private ColorChecker full-image file as RGB ndarray.
    将内部完整校色图读取为 RGB ndarray。
    """
    path = resolve_colorchecker_full_path(registry, file_id)
    try:
        with Image.open(path) as image:
            return np.array(image.convert("RGB"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Unable to read ColorChecker calibrated image: {exc}") from exc


def resolve_colorchecker_source_file(registry: FileRegistry, file_id: str) -> tuple[str, str]:
    """Resolve a private ColorChecker source file id to a local path.
    将内部 ColorChecker 源图 file id 解析为本地路径。
    """
    if not file_id:
        raise HTTPException(status_code=422, detail="ColorChecker source file id is required")
    entry = registry.get_entry(file_id)
    if (
        entry is None
        or entry.get("purpose") != COLORCHECKER_SOURCE_PURPOSE
        or entry.get("is_public") is not False
    ):
        raise HTTPException(status_code=404, detail="ColorChecker source image not found or expired")
    result = registry.resolve(file_id)
    if result is None:
        raise HTTPException(status_code=404, detail="ColorChecker source image not found or expired")
    return result


def cleanup_colorchecker_private_file(registry: FileRegistry, file_id: str) -> bool:
    """Delete one private ColorChecker source or calibrated artifact.
    删除一个 ColorChecker 内部源图或完整校色图产物。
    """
    entry = registry.get_entry(file_id)
    if entry is None:
        return False
    if (
        entry.get("purpose") not in _COLORCHECKER_PRIVATE_PURPOSES
        or entry.get("is_public") is not False
    ):
        raise HTTPException(status_code=403, detail="Only ColorChecker private artifacts can be released")
    return registry.cleanup_file(file_id) > 0


def cleanup_colorchecker_full_file(registry: FileRegistry, file_id: str) -> bool:
    """Delete one private ColorChecker full-image artifact when it exists.
    删除一个存在的内部完整校色图产物。
    """
    return cleanup_colorchecker_private_file(registry, file_id)


def confirm_colorchecker_full_file(registry: FileRegistry, file_id: str) -> bool:
    """Mark a pending private ColorChecker full-image artifact as confirmed.
    将待确认的内部完整校色图标记为用户已确认。
    """
    entry = registry.get_entry(file_id)
    if (
        entry is None
        or entry.get("purpose") not in _COLORCHECKER_FULL_PURPOSES
        or entry.get("is_public") is not False
    ):
        raise HTTPException(status_code=404, detail="ColorChecker calibrated image not found or expired")
    if registry.resolve(file_id) is None:
        raise HTTPException(status_code=404, detail="ColorChecker calibrated image not found or expired")
    if entry.get("purpose") == COLORCHECKER_FULL_PURPOSE:
        return True
    return registry.set_purpose(file_id, COLORCHECKER_FULL_PURPOSE)


def touch_colorchecker_full_file(registry: FileRegistry, file_id: str) -> bool:
    """Renew one pending or confirmed private ColorChecker full-image artifact.
    续期一个待确认或已确认的内部完整校色图产物。
    """
    entry = registry.get_entry(file_id)
    if (
        entry is None
        or entry.get("purpose") not in _COLORCHECKER_FULL_PURPOSES
        or entry.get("is_public") is not False
    ):
        raise HTTPException(status_code=404, detail="ColorChecker calibrated image not found or expired")
    if registry.resolve(file_id) is None:
        raise HTTPException(status_code=404, detail="ColorChecker calibrated image not found or expired")
    return True


def touch_colorchecker_private_file(registry: FileRegistry, file_id: str) -> bool:
    """Renew one private ColorChecker source or calibrated artifact.
    续期一个 ColorChecker 内部源图或完整校色图产物。
    """
    entry = registry.get_entry(file_id)
    if (
        entry is None
        or entry.get("purpose") not in _COLORCHECKER_PRIVATE_PURPOSES
        or entry.get("is_public") is not False
    ):
        raise HTTPException(status_code=404, detail="ColorChecker private artifact not found or expired")
    if registry.resolve(file_id) is None:
        raise HTTPException(status_code=404, detail="ColorChecker private artifact not found or expired")
    return True


def scale_corner_points(
    points: Sequence[Sequence[float]],
    *,
    source_width: float | None,
    source_height: float | None,
    target_width: int,
    target_height: int,
) -> list[list[int]]:
    """Scale corner coordinates from preview space to full-image space.
    将预览坐标空间中的角点缩放到完整图坐标空间。
    """
    if not source_width or not source_height or source_width <= 0 or source_height <= 0:
        return [[int(round(point[0])), int(round(point[1]))] for point in points]
    scale_x = float(target_width) / float(source_width)
    scale_y = float(target_height) / float(source_height)
    return [
        [
            int(round(float(point[0]) * scale_x)),
            int(round(float(point[1]) * scale_y)),
        ]
        for point in points
    ]
