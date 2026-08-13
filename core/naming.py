"""Naming_Service — 统一的文件命名服务模块。

负责生成 Lumina Studio 中所有输出文件的标准化文件名，
包含时间戳和模式信息，便于用户识别和管理生成的文件。
"""

import re
import uuid
from datetime import datetime
from typing import Optional, Dict

from config import ModelingMode

# 建模模式 → 文件名标识映射
MODELING_MODE_TAGS: Dict[ModelingMode, str] = {
    ModelingMode.HIGH_FIDELITY: "HiFi",
    ModelingMode.PIXEL: "Pixel",
    ModelingMode.VECTOR: "Vector",
    ModelingMode.COLOR_CARD: "ColorCard",
}

# 颜色模式 → 文件名标识映射
COLOR_MODE_TAGS: Dict[str, str] = {
    "4-Color": "4C",
    "4-Color (1024 colors)": "4C",
    "4-Color (CMYW)": "4C",
    "4-Color (RYBW)": "4C",
    "CMYW": "4C",
    "RYBW": "4C",
    "5-Color Extended": "5C",
    "6-Color": "6C",
    "6-Color (CMYWGK 1296)": "6C",
    "6-Color (RYBWGK 1296)": "6C",
    "8-Color Max": "8C",
    "8-Color": "8C",
    "BW": "BW",
    "BW (Black & White)": "BW",
    "Merged": "Merged",
}


def _get_timestamp() -> str:
    """返回当前本地时间的时间戳字符串，格式 YYYYMMDD_HHmmss。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sanitize(name: str) -> str:
    """移除文件名中操作系统不允许的特殊字符，替换为下划线。"""
    forbidden = '<>:"/\\|?*'
    for ch in forbidden:
        name = name.replace(ch, "_")
    return name


# Legacy uploader/pywebview temporary file prefix pattern: tmp{random}_
# (e.g. tmpq7esd8mm_photo, tmpud7d8o06_photo)
_TEMP_PREFIX_RE = re.compile(r"^tmp[a-zA-Z0-9]{4,12}_")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_RESERVED_NAME_RE = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]) *(?:\.|$)",
    re.IGNORECASE,
)
_PRESERVED_3MF_EXTENSION = ".3mf"
_MAX_FILENAME_COMPONENT_BYTES = 255
_MAX_PRESERVED_3MF_STEM_BYTES = (
    _MAX_FILENAME_COMPONENT_BYTES - len(_PRESERVED_3MF_EXTENSION.encode("utf-8"))
)


def _strip_temp_prefix(name: str) -> str:
    """去除上传器/pywebview 生成的临时文件名前缀。"""
    return _TEMP_PREFIX_RE.sub("", name)


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Truncate text to a UTF-8 byte limit without splitting a code point."""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def generate_preserved_upload_3mf_filename(
    source_basename: str | None,
) -> str | None:
    """Build a safe 3MF download name from an uploaded source basename.

    根据上传文件的无扩展名名称生成安全的 3MF 下载文件名。

    Args:
        source_basename: Extension-free basename captured from upload metadata.
            从上传元数据中取得的无扩展名文件名。

    Returns:
        A safe ``.3mf`` filename, or ``None`` when no usable stem remains.
        安全的 ``.3mf`` 文件名；无法得到有效名称时返回 ``None``。
    """
    stem = str(source_basename or "").strip()
    if not stem:
        return None
    stem = _strip_temp_prefix(stem)
    stem = _CONTROL_CHAR_RE.sub("_", stem)
    stem = _sanitize(stem).strip(" .")
    stem = _truncate_utf8(stem, _MAX_PRESERVED_3MF_STEM_BYTES).rstrip(" .")
    if not stem:
        return None
    if _WINDOWS_RESERVED_NAME_RE.match(stem):
        stem = _truncate_utf8(
            f"_{stem}",
            _MAX_PRESERVED_3MF_STEM_BYTES,
        ).rstrip(" .")
    return f"{stem}{_PRESERVED_3MF_EXTENSION}"


def generate_model_filename(
    base_name: str,
    modeling_mode: ModelingMode,
    color_mode: str,
    extension: str = ".3mf",
) -> str:
    """生成标准模型文件名。

    格式: {base_name}_Lumina_{mode_tag}_{color_tag}_{timestamp}{ext}

    - base_name 为空字符串时使用默认值 "untitled"
    - modeling_mode 未知时使用 "Unknown" 作为 mode tag
    - color_mode 未知时使用 "Unknown" 作为 color tag
    """
    base = _sanitize(_strip_temp_prefix(base_name.strip())) if base_name.strip() else "untitled"
    mode_tag = MODELING_MODE_TAGS.get(modeling_mode, "Unknown")
    color_tag = COLOR_MODE_TAGS.get(color_mode, "Unknown")
    ts = _get_timestamp()
    return f"{base}_Lumina_{mode_tag}_{color_tag}_{ts}{extension}"


def generate_preview_filename(
    base_name: str,
    extension: str = ".glb",
) -> str:
    """生成预览文件名。

    格式: {base_name}_Preview_{timestamp}{ext}

    - base_name 为空字符串时使用默认值 "untitled"
    """
    base = _sanitize(_strip_temp_prefix(base_name.strip())) if base_name.strip() else "untitled"
    ts = _get_timestamp()
    return f"{base}_Preview_{ts}{extension}"


def generate_segmented_glb_filename(
    session_id: Optional[str],
    extension: str = ".glb",
) -> str:
    """Generate a session-scoped, collision-free filename for segmented GLB output.
    生成按会话隔离且不会冲突的分色 GLB 输出文件名。

    Combines a short session_id prefix (for traceability in OUTPUT_DIR listings
    and log correlation) with a uuid4 segment (for uniqueness even when the
    same session triggers multiple concurrent GLB builds within the same
    second). API endpoints that expose ``/api/files/{glb_id}`` rely on this
    so cross-session writes never overwrite each other on disk.
    将 session_id 前 8 位（便于在 OUTPUT_DIR 列表与日志中追溯）与 uuid4 短段
    （即便同一会话在同一秒内并发触发多次 GLB 生成也保持唯一）拼接。暴露
    ``/api/files/{glb_id}`` 的 API 端点依赖该助手，确保跨会话写入不会在磁盘
    上互相覆盖。

    Format / 格式: ``segmented_{session_prefix}_{uuid12}{extension}``

    Args:
        session_id (str | None): Caller's session identifier. ``None`` or empty
            falls back to ``"anon"`` so the helper never raises on missing sessions.
            (会话标识；``None`` 或空字符串回退为 ``"anon"``，确保调用永远不抛错)
        extension (str): File extension including the leading dot. Default ``.glb``.
            (含前导点的扩展名，默认 ``.glb``)

    Returns:
        str: Collision-free basename safe for ``os.path.join(OUTPUT_DIR, ...)``.
            (可直接拼到 ``OUTPUT_DIR`` 后的无冲突文件名)
    """
    raw_prefix = (session_id or "anon")[:8] or "anon"
    safe_prefix = _sanitize(raw_prefix)
    rand = uuid.uuid4().hex[:12]
    return f"segmented_{safe_prefix}_{rand}{extension}"


def generate_calibration_filename(
    color_mode: str,
    calibration_type: str = "Standard",
    extension: str = ".3mf",
) -> str:
    """生成校准板文件名。

    格式: Lumina_Calibration_{calibration_type}_{color_tag}_{timestamp}{ext}

    - color_mode 未知时使用 "Unknown" 作为 color tag
    """
    color_tag = COLOR_MODE_TAGS.get(color_mode, "Unknown")
    safe_type = _sanitize(calibration_type)
    ts = _get_timestamp()
    return f"Lumina_Calibration_{safe_type}_{color_tag}_{ts}{extension}"


def generate_batch_filename(
    extension: str = ".zip",
) -> str:
    """生成批量输出文件名。

    格式: Lumina_Batch_{timestamp}{ext}
    """
    ts = _get_timestamp()
    return f"Lumina_Batch_{ts}{extension}"


# Timestamp pattern: YYYYMMDD_HHmmss
_TS_PATTERN = r"\d{8}_\d{6}"

# Valid mode and color tags for matching
_VALID_MODE_TAGS = {"HiFi", "Pixel", "Vector", "ColorCard"}
_VALID_COLOR_TAGS = {"4C", "5C", "6C", "8C", "BW", "Merged"}

# Regex patterns for each file type
_MODEL_RE = re.compile(rf"^(.+)_Lumina_(HiFi|Pixel|Vector|ColorCard)_(4C|5C|6C|8C|BW|Merged)_({_TS_PATTERN})(\.[\w]+)$")
_PREVIEW_RE = re.compile(rf"^(.+)_Preview_({_TS_PATTERN})(\.[\w]+)$")
_CALIBRATION_RE = re.compile(rf"^Lumina_Calibration_(.+?)_(4C|5C|6C|8C|BW|Merged)_({_TS_PATTERN})(\.[\w]+)$")
_BATCH_RE = re.compile(rf"^Lumina_Batch_({_TS_PATTERN})(\.[\w]+)$")


def parse_filename(filename: str) -> Optional[Dict[str, str]]:
    """从标准化文件名中解析各组成部分。

    返回 dict 包含 base_name, modeling_mode, color_mode, timestamp, extension 等字段。
    非标准格式返回 None，不抛出异常。
    """
    try:
        if not isinstance(filename, str) or not filename:
            return None

        # Try model filename pattern
        m = _MODEL_RE.match(filename)
        if m:
            return {
                "base_name": m.group(1),
                "modeling_mode": m.group(2),
                "color_mode": m.group(3),
                "timestamp": m.group(4),
                "extension": m.group(5),
                "file_type": "model",
            }

        # Try preview filename pattern
        m = _PREVIEW_RE.match(filename)
        if m:
            return {
                "base_name": m.group(1),
                "modeling_mode": None,
                "color_mode": None,
                "timestamp": m.group(2),
                "extension": m.group(3),
                "file_type": "preview",
            }

        # Try calibration filename pattern
        m = _CALIBRATION_RE.match(filename)
        if m:
            return {
                "base_name": "Lumina_Calibration",
                "modeling_mode": None,
                "color_mode": m.group(2),
                "calibration_type": m.group(1),
                "timestamp": m.group(3),
                "extension": m.group(4),
                "file_type": "calibration",
            }

        # Try batch filename pattern
        m = _BATCH_RE.match(filename)
        if m:
            return {
                "base_name": "Lumina_Batch",
                "modeling_mode": None,
                "color_mode": None,
                "timestamp": m.group(1),
                "extension": m.group(2),
                "file_type": "batch",
            }

        # Non-standard format
        return None
    except Exception:
        return None
