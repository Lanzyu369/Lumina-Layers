"""Ticket directory assembly for the reproducible bug-report pipeline.

反馈工单目录装配：同步部分（原图 / 生成产物 / LUT）+ 异步部分（耗材 zip、
index.md、summary.txt、上传官方反馈服务）+ 启动时清理。

Design (`.kiro/specs/reproducible-bug-reports/design.md` §Components §5):

* Sync path ``collect_sync_attachments`` runs inside the HTTP handler so the
  response waits only on small file copies + sha256 (bounded to ~2 s).
* Async path ``finalize_ticket_async`` runs via FastAPI BackgroundTasks; it
  packs ``materials.zip``, renders ``index.md`` / ``summary.txt``, and
  uploads the ticket to the official feedback server. All steps are independently try/except so a
  single failure downgrades the ticket to ``assembly_status='partial_failed'``
  but never crashes the background worker pool.
* ``run_startup_cleanup`` purges bulky attachments that outlived their TTL
  and marks abandoned in-flight tickets as ``interrupted``.

同步装配只做小文件拷贝与指纹（HTTP 请求内 ≤2 秒），其余大头（耗材 zip、
渲染索引、上传工单）放后台任务。启动时清理按 TTL 删除大附件，并把异常残留
的装配中工单标为 interrupted。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pathlib import PurePath, PureWindowsPath
from typing import Any, Iterable
from urllib.parse import urlparse

from starlette.datastructures import UploadFile

from api.feedback_config import (
    materials_bundle_timeout_s,
    ticket_attachment_ttl_days,
)
from api.feedback_fingerprint import file_sha256, guess_mime
from api.feedback_hosted import submit_ticket_directory
from api.feedback_index import generate_index_markdown, generate_summary_text
from api.feedback_materials_bundle import pack_materials
from api.feedback_time import now_beijing
from api.file_bridge import SUPPORTED_UPLOAD_IMAGE_EXTENSIONS
from api.structured_logging import get_logger
from config import TEMP_DIR
from utils.lut_manager import LUTManager

__all__ = [
    "MAX_DIRECT_ORIGINAL_IMAGE_BYTES",
    "SyncCollectionResult",
    "collect_direct_original_upload",
    "collect_sync_attachments",
    "finalize_ticket_async",
    "resubmit_ticket_async",
    "run_startup_cleanup",
]


@dataclass(frozen=True)
class SyncCollectionResult:
    """Outcome of :func:`collect_sync_attachments` for one ticket.

    :func:`collect_sync_attachments` 的返回结构。
    """

    original_image: dict[str, Any]
    final_artifact: dict[str, Any]
    lut: dict[str, Any]


log = get_logger(__name__)


REPO_ROOT = Path(__file__).resolve().parent.parent

MAX_DIRECT_ORIGINAL_IMAGE_BYTES = 100 * 1024 * 1024
"""Maximum exact browser-source attachment size: 100 MiB.

浏览器直接附带原图的最大尺寸：100 MiB。
"""

_DIRECT_UPLOAD_CHUNK_BYTES = 1024 * 1024

_IMAGE_EXTENSIONS = SUPPORTED_UPLOAD_IMAGE_EXTENSIONS
_FINAL_ARTIFACT_EXTENSIONS = frozenset((".3mf", ".zip"))
_LUT_EXTENSIONS = (".npy", ".json", ".npz", ".msgpack")
_PREVIEW_STOPWORDS = ("preview", "layer", "swatch", "overlay", "warp")

_BULKY_ATTACHMENT_GLOBS = (
    "original.*",
    "final.*",
    "lut.*",
    "materials.zip",
    "screenshot.*",
)
_STARTUP_INTERRUPTED_AFTER_MINUTES = 10


# ---------------------------------------------------------------------------
# Sync attachment collection
# ---------------------------------------------------------------------------


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _direct_original_result(
    *,
    status: str,
    session_id: str | None,
    direct_upload_status: str,
    error_type: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "mime_type": None,
        "source_session_id": session_id,
        "capture_source": None,
        "direct_upload_status": direct_upload_status,
    }
    if error_type is not None:
        result["error_type"] = error_type
    if error_message is not None:
        result["error_message"] = error_message
    return result


def _direct_upload_suffix(filename: str | None) -> str | None:
    if not filename:
        return None
    suffix = (
        PureWindowsPath(filename).suffix
        if "\\" in filename
        else PurePath(filename).suffix
    ).lower()
    return suffix if suffix in SUPPORTED_UPLOAD_IMAGE_EXTENSIONS else None


async def collect_direct_original_upload(
    ticket_dir: Path,
    upload: UploadFile | None,
    *,
    session_id: str | None,
    omission_reason: str | None = None,
) -> dict[str, Any]:
    """Persist an exact browser-provided converter source image.

    保存浏览器直接提供的 Converter 原始输入文件，保持字节不变。

    Args:
        ticket_dir: Reserved ticket directory. / 已预留的工单目录。
        upload: Optional multipart upload. / 可选 multipart 文件。
        session_id: Related converter session when available. / 可用的会话 ID。
        omission_reason: Client-declared omission reason, currently
            ``"too_large"`` only. / 客户端声明的省略原因，目前仅支持超限。

    Returns:
        dict[str, Any]: Attachment manifest fragment. / 附件清单片段。
    """
    if omission_reason == "too_large":
        return _direct_original_result(
            status="too_large",
            session_id=session_id,
            direct_upload_status="too_large",
            error_type="OriginalImageTooLarge",
            error_message="Original image exceeds the 100 MiB direct-upload limit.",
        )
    if upload is None:
        return _direct_original_result(
            status="not_provided",
            session_id=session_id,
            direct_upload_status="not_provided",
        )

    suffix = _direct_upload_suffix(upload.filename)
    if suffix is None:
        return _direct_original_result(
            status="failed",
            session_id=session_id,
            direct_upload_status="failed",
            error_type="UnsupportedOriginalImageType",
            error_message="Original image type is not supported.",
        )
    if upload.size is not None and upload.size > MAX_DIRECT_ORIGINAL_IMAGE_BYTES:
        return _direct_original_result(
            status="too_large",
            session_id=session_id,
            direct_upload_status="too_large",
            error_type="OriginalImageTooLarge",
            error_message="Original image exceeds the 100 MiB direct-upload limit.",
        )

    destination = ticket_dir / f"original{suffix}"
    digest = hashlib.sha256()
    total_bytes = 0
    destination_created = False
    try:
        await upload.seek(0)
        with destination.open("xb") as output:
            destination_created = True
            while True:
                chunk = await upload.read(_DIRECT_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_DIRECT_ORIGINAL_IMAGE_BYTES:
                    raise ValueError("OriginalImageTooLarge")
                written = output.write(chunk)
                if written != len(chunk):
                    raise OSError(
                        "Short write while saving the direct original image."
                    )
                digest.update(chunk)
    except Exception as exc:  # noqa: BLE001 - attachment boundary must not abort report.
        if destination_created:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        too_large = isinstance(exc, ValueError) and str(exc) == "OriginalImageTooLarge"
        log.warning(
            "Direct original-image upload failed.",
            extra={
                "event": "feedback_attachment_collection_failed",
                "attachment_kind": "original_image",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "ticket_id": ticket_dir.name,
            },
        )
        return _direct_original_result(
            status="too_large" if too_large else "failed",
            session_id=session_id,
            direct_upload_status="too_large" if too_large else "failed",
            error_type="OriginalImageTooLarge" if too_large else type(exc).__name__,
            error_message=(
                "Original image exceeds the 100 MiB direct-upload limit."
                if too_large
                else "Original image could not be saved."
            ),
        )

    return {
        "status": "attached",
        "filename": destination.name,
        "sha256": digest.hexdigest(),
        "size_bytes": total_bytes,
        "mime_type": guess_mime(destination),
        "source_session_id": session_id,
        "capture_source": "browser_upload",
        "direct_upload_status": "attached",
    }


def _failed_original_image(
    session_id: str | None,
    error_type: str,
    error_message: str,
    *,
    direct_upload_status: str = "not_provided",
) -> dict[str, Any]:
    return {
        "status": "failed",
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "mime_type": None,
        "source_session_id": session_id,
        "capture_source": None,
        "direct_upload_status": direct_upload_status,
        "error_type": error_type,
        "error_message": error_message,
    }


def _failed_final_artifact(
    session_id: str | None,
    artifact_type: str | None,
    error_type: str,
    error_message: str,
    *,
    history_count: int = 0,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "artifact_type": artifact_type,
        "source_session_id": session_id,
        "generated_at": None,
        "history_count": history_count,
        "error_type": error_type,
        "error_message": error_message,
    }


def _failed_lut(
    lut_name: str | None,
    kind: str | None,
    error_type: str,
    error_message: str,
    *,
    preset_relative_path: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "kind": kind,
        "name": lut_name,
        "preset_relative_path": preset_relative_path,
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "metadata": {},
        "error_type": error_type,
        "error_message": error_message,
    }


def _empty_lut_attachment() -> dict[str, Any]:
    """Return the default LUT attachment shape.

    返回 LUT 附件默认结构，保证单选、多选、缺失路径字段一致。
    """

    return {
        "status": "not_applicable",
        "kind": None,
        "name": None,
        "preset_relative_path": None,
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "metadata": {},
    }


def _original_image_expected(context: dict[str, Any]) -> bool:
    ref = context.get("active_original_image_ref")
    return isinstance(ref, dict) and (
        _is_non_empty_string(ref.get("session_id"))
        or (
            ref.get("source") == "converter"
            and _is_non_empty_string(ref.get("filename"))
        )
    )


def _final_artifact_expected(context: dict[str, Any]) -> bool:
    ref = context.get("active_final_artifact_ref")
    return (
        isinstance(ref, dict)
        and (
            _is_non_empty_string(ref.get("session_id"))
            or _is_non_empty_string(ref.get("download_url"))
            or _is_non_empty_string(ref.get("disk_path"))
        )
    )


def _lut_expected(context: dict[str, Any]) -> bool:
    source_version = context.get("source_version")
    return (
        source_version in {None, "legacy"}
        and len(_lut_names_from_context(context)) > 0
    )


def _lut_critical_for_finalize(context: dict[str, Any]) -> bool:
    return context.get("active_tab") == "converter" and _lut_expected(context)


def _lut_names_from_context(context: dict[str, Any]) -> list[str]:
    """Return bounded, de-duplicated legacy LUT names from bug context.

    从 bug 上下文提取有界、去重的传统 LUT 名称列表。
    """

    names: list[str] = []
    primary = context.get("lut_name")
    if _is_non_empty_string(primary):
        names.append(str(primary).strip())
    raw_names = context.get("lut_names")
    if isinstance(raw_names, list):
        for item in raw_names:
            if not _is_non_empty_string(item):
                continue
            clean = str(item).strip()
            if clean and clean not in names:
                names.append(clean)
            if len(names) >= 32:
                break
    return names


def _file_registry_entries_for(file_registry, session_id: str | None) -> dict[str, dict]:
    """Return FileRegistry entries for ``session_id`` (empty dict on None)."""
    if not session_id:
        return {}
    try:
        return file_registry.get_session_entries(session_id)
    except Exception:
        # FileRegistry must not bring down ticket assembly.
        return {}


def _pick_original_image_entry(
    entries: dict[str, dict],
) -> tuple[str, dict] | None:
    """Pick the most likely user-uploaded image from ``entries``.

    启发式：扩展名是图片；文件名不包含预览/合成等停用词；取最早创建的。
    """
    candidates: list[tuple[float, str, dict]] = []
    for fid, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        filename = str(entry.get("filename") or Path(entry.get("path", "")).name)
        lower = filename.lower()
        if Path(lower).suffix not in _IMAGE_EXTENSIONS:
            continue
        if any(word in lower for word in _PREVIEW_STOPWORDS):
            continue
        created_at = entry.get("created_at") or 0
        try:
            created_at = float(created_at)
        except (TypeError, ValueError):
            created_at = 0.0
        candidates.append((created_at, fid, entry))
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0])
    _, fid, entry = candidates[0]
    return fid, entry


def _pick_final_artifact_entry(
    entries: dict[str, dict],
) -> tuple[str, dict, int]:
    """Pick the most recent .3mf / .zip from ``entries`` + total matching count.

    选取最新的 .3mf / .zip 条目，同时返回匹配总数（作为 history_count）。
    """
    matches: list[tuple[float, str, dict]] = []
    for fid, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        filename = str(entry.get("filename") or Path(entry.get("path", "")).name)
        if Path(filename.lower()).suffix not in _FINAL_ARTIFACT_EXTENSIONS:
            continue
        created_at = entry.get("created_at") or 0
        try:
            created_at = float(created_at)
        except (TypeError, ValueError):
            created_at = 0.0
        matches.append((created_at, fid, entry))
    if not matches:
        return ("", {}, 0)
    matches.sort(key=lambda row: row[0], reverse=True)
    _, fid, entry = matches[0]
    return fid, entry, len(matches)


def _extract_file_id_from_download_url(download_url: str | None) -> str | None:
    """Extract a FileRegistry id from ``/api/files/<id>`` URLs.

    从 ``/api/files/<id>`` 下载地址中提取 FileRegistry id。
    """
    if not isinstance(download_url, str) or not download_url.strip():
        return None
    try:
        parsed = urlparse(download_url.strip())
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    path = parsed.path
    prefix = "/api/files/"
    if not path.startswith(prefix):
        return None
    file_id = path[len(prefix):].strip()
    if (
        not file_id
        or file_id in {".", ".."}
        or "/" in file_id
        or "\\" in file_id
        or any(char.isspace() for char in file_id)
    ):
        return None
    return file_id


def _collect_final_artifact_from_download_url(
    ticket_dir: Path,
    file_registry,
    download_url: str | None,
    artifact_type: str | None,
    session_id: str | None,
) -> dict[str, Any] | None:
    """Copy the exact artifact referenced by a frontend download URL.

    复制前端下载地址精确指向的产物。
    """
    file_id = _extract_file_id_from_download_url(download_url)
    if file_id is None:
        return None
    get_entry = getattr(file_registry, "get_entry", None)
    if not callable(get_entry):
        return None
    try:
        entry = get_entry(file_id)
    except Exception as exc:
        return _failed_final_artifact(
            session_id,
            artifact_type,
            type(exc).__name__,
            "Final artifact could not be saved.",
        )
    if not isinstance(entry, dict) or entry.get("is_public") is False:
        return None
    if (
        entry.get("lifecycle") == "session_bound"
        and entry.get("session_id") != session_id
    ):
        return None
    resolve = getattr(file_registry, "resolve", None)
    if not callable(resolve):
        return None
    try:
        resolved = resolve(file_id)
    except Exception as exc:
        return _failed_final_artifact(
            session_id,
            artifact_type,
            type(exc).__name__,
            "Final artifact could not be saved.",
        )
    if resolved is None:
        return None
    try:
        src_path_raw, filename = resolved
        src_path = Path(src_path_raw)
    except (TypeError, ValueError):
        return None
    candidate_name = str(filename or src_path.name)
    suffix = Path(candidate_name).suffix.lower() or src_path.suffix.lower()
    if suffix not in _FINAL_ARTIFACT_EXTENSIONS or not src_path.is_file():
        return None

    dst = ticket_dir / f"final{suffix}"
    try:
        shutil.copy2(src_path, dst)
        size = dst.stat().st_size
        sha = file_sha256(dst)
    except OSError as exc:
        try:
            dst.unlink()
        except OSError:
            pass
        return _failed_final_artifact(
            session_id,
            artifact_type,
            type(exc).__name__,
            "Final artifact could not be saved.",
            history_count=1,
        )
    created_at = entry.get("created_at") if isinstance(entry, dict) else None
    return {
        "status": "attached",
        "filename": dst.name,
        "sha256": sha,
        "size_bytes": size,
        "artifact_type": suffix.lstrip(".") or artifact_type,
        "source_session_id": session_id,
        "generated_at": _format_created_at(created_at),
        "history_count": 1,
    }


def _find_lut_file(lut_name: str) -> Path | None:
    """Locate LUTs in preset or configured shared writable roots.

    先精确匹配，再大小写不敏感；按 .npy/.json/.npz/.msgpack 的优先顺序取。
    """
    if not _is_lut_name_path_safe(lut_name):
        return None
    lut_preset_dir = _safe_lut_preset_root()
    display_match = LUTManager.get_lut_path(lut_name)
    if display_match:
        for root in (
            lut_preset_dir,
            LUTManager.custom_lut_dir().resolve(),
            LUTManager.cloud_lut_dir().resolve(),
        ):
            found = _lut_file_within_root(Path(display_match), root)
            if found is not None:
                return found

    if not lut_preset_dir.is_dir():
        return None

    for ext in _LUT_EXTENSIONS:
        exact = lut_preset_dir / f"{lut_name}{ext}"
        found = _lut_file_within_root(exact, lut_preset_dir)
        if found is not None:
            return found
    # Case-insensitive fallback: search children.
    try:
        lowered = lut_name.lower()
        for path in lut_preset_dir.rglob("*"):
            if path.stem.lower() != lowered:
                continue
            found = _lut_file_within_root(path, lut_preset_dir)
            if found is not None:
                return found
    except OSError:
        return None
    return None


def _is_lut_name_path_safe(lut_name: object) -> bool:
    """Return whether a client LUT name is safe to use for lookup."""

    if not isinstance(lut_name, str) or not lut_name.strip():
        return False
    if "/" in lut_name or "\\" in lut_name:
        return False
    if PurePath(lut_name).is_absolute() or PureWindowsPath(lut_name).is_absolute():
        return False
    path_parts = (*PurePath(lut_name).parts, *PureWindowsPath(lut_name).parts)
    return ".." not in path_parts


def _safe_lut_preset_root() -> Path:
    return (REPO_ROOT / "lut-preset").resolve()


def _lut_file_within_root(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve()
        if not resolved.is_file():
            return None
        if resolved.suffix.lower() not in _LUT_EXTENSIONS:
            return None
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _format_created_at(value: Any) -> str | None:
    """Convert a float epoch seconds to ISO-UTC Z format, best-effort."""
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OSError, ValueError, OverflowError):
        return None


def _public_ticket_path(ticket_dir: Path) -> str:
    """Return the logical ticket location for user-facing channels."""

    return f"feedback/{ticket_dir.parent.name}/{ticket_dir.name}"


def collect_sync_attachments(
    ticket_dir: Path,
    payload: dict[str, Any],
    file_registry,
    now: datetime | None = None,
    session_store=None,
) -> SyncCollectionResult:
    """Collect original image / final artifact / LUT into ``ticket_dir``.

    同步地把原图、最终产物、LUT 拷进工单目录，并返回装配结果。
    调用方有责任把返回的三段并进 `payload['attachments']` 并重写
    ticket.json；本函数本身不再二次写回。

    Never raises for recoverable issues — each sub-step is guarded with
    try/except so the result always ends up with a consistent attachments
    block even when one sub-step fails.
    每个子步骤独立 try/except，保证最终结果里每个字段自洽。
    """
    del now  # Reserved for future time-based TTL policies.
    ticket_id = payload.get("ticket_id")
    raw_context = payload.get("context")
    context = raw_context if isinstance(raw_context, dict) else {}

    # Defaults used when a sub-step bails early.
    default_original = {
        "status": "not_applicable",
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "mime_type": None,
        "source_session_id": None,
        "capture_source": None,
        "direct_upload_status": "not_provided",
    }
    default_final = {
        "status": "not_applicable",
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "artifact_type": None,
        "source_session_id": None,
        "generated_at": None,
        "history_count": 0,
    }
    default_lut = {
        "status": "not_applicable",
        "kind": None,
        "name": None,
        "preset_relative_path": None,
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "metadata": {},
    }

    original = default_original
    final = default_final
    lut = default_lut

    # --- Original image -----------------------------------------------------
    try:
        ref = context.get("active_original_image_ref") or {}
        session_id = ref.get("session_id") if isinstance(ref, dict) else None
        attachment_manifest = payload.get("attachments")
        manifest_original = (
            attachment_manifest.get("original_image")
            if isinstance(attachment_manifest, dict)
            else None
        )
        direct_candidate = (
            manifest_original
            if isinstance(manifest_original, dict)
            and manifest_original.get("direct_upload_status")
            in {"attached", "too_large", "failed"}
            else _direct_original_result(
                status="not_provided",
                session_id=session_id,
                direct_upload_status="not_provided",
            )
        )
        if direct_candidate.get("status") == "attached":
            original = direct_candidate
        else:
            fallback = _collect_original_image(
                ticket_dir,
                file_registry,
                session_id,
                session_store=session_store,
            )
            if (
                fallback.get("status") == "not_applicable"
                and _original_image_expected(context)
            ):
                fallback = {**fallback, "status": "unavailable_after_cleanup"}
            if fallback.get("status") == "attached":
                original = {
                    **fallback,
                    "direct_upload_status": direct_candidate.get(
                        "direct_upload_status", "not_provided"
                    ),
                }
            elif direct_candidate.get("status") in {"too_large", "failed"}:
                original = {
                    **direct_candidate,
                    "source_session_id": session_id,
                }
            else:
                original = {
                    **fallback,
                    "direct_upload_status": direct_candidate.get(
                        "direct_upload_status", "not_provided"
                    ),
                }
        log.info(
            "Attachment collected.",
            extra={
                "event": "feedback_attachment_collected",
                "attachment_kind": "original_image",
                "status": original["status"],
                "capture_source": original.get("capture_source"),
                "direct_upload_status": original.get("direct_upload_status"),
                "ticket_id": ticket_id,
            },
        )
    except Exception as exc:
        if _original_image_expected(context):
            ref = context.get("active_original_image_ref") or {}
            session_id = ref.get("session_id") if isinstance(ref, dict) else None
            original = _failed_original_image(
                session_id,
                type(exc).__name__,
                "Original image could not be saved.",
            )
        log.warning(
            "Original-image collection crashed.",
            extra={
                "event": "feedback_attachment_collection_failed",
                "attachment_kind": "original_image",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "ticket_id": ticket_id,
            },
        )

    # --- Final artifact -----------------------------------------------------
    try:
        ref = context.get("active_final_artifact_ref") or {}
        session_id = ref.get("session_id") if isinstance(ref, dict) else None
        artifact_type = ref.get("artifact_type") if isinstance(ref, dict) else None
        download_url = ref.get("download_url") if isinstance(ref, dict) else None
        final = _collect_final_artifact(
            ticket_dir, file_registry, session_id, artifact_type,
            download_url=download_url,
        )
        if _final_artifact_expected(context) and final.get("status") == "not_applicable":
            final = {**final, "status": "expired_ttl"}
        log.info(
            "Attachment collected.",
            extra={
                "event": "feedback_attachment_collected",
                "attachment_kind": "final_artifact",
                "status": final["status"],
                "ticket_id": ticket_id,
            },
        )
    except Exception as exc:
        if _final_artifact_expected(context):
            ref = context.get("active_final_artifact_ref") or {}
            session_id = ref.get("session_id") if isinstance(ref, dict) else None
            artifact_type = ref.get("artifact_type") if isinstance(ref, dict) else None
            final = _failed_final_artifact(
                session_id,
                artifact_type,
                type(exc).__name__,
                "Final artifact could not be saved.",
            )
        log.warning(
            "Final-artifact collection crashed.",
            extra={
                "event": "feedback_attachment_collection_failed",
                "attachment_kind": "final_artifact",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "ticket_id": ticket_id,
            },
        )

    # --- LUT ----------------------------------------------------------------
    try:
        lut = _collect_lut(ticket_dir, context)
        log.info(
            "Attachment collected.",
            extra={
                "event": "feedback_attachment_collected",
                "attachment_kind": "lut",
                "status": lut["status"],
                "ticket_id": ticket_id,
            },
        )
    except Exception as exc:
        if _lut_expected(context):
            lut_names = _lut_names_from_context(context)
            lut = _failed_lut(
                lut_names[0] if lut_names else None,
                None,
                type(exc).__name__,
                "LUT could not be saved.",
            )
            if len(lut_names) > 1:
                lut["names"] = lut_names
        log.warning(
            "LUT collection crashed.",
            extra={
                "event": "feedback_attachment_collection_failed",
                "attachment_kind": "lut",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "ticket_id": ticket_id,
            },
        )

    return SyncCollectionResult(
        original_image=original, final_artifact=final, lut=lut,
    )


def _collect_original_image(
    ticket_dir: Path,
    file_registry,
    session_id: str | None,
    *,
    session_store=None,
) -> dict[str, Any]:
    """Build the ``original_image`` attachment dict."""
    default_missing = {
        "status": "not_applicable",
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "mime_type": None,
        "source_session_id": session_id,
        "capture_source": None,
        "direct_upload_status": "not_provided",
    }
    if not session_id:
        return default_missing

    unavailable = {
        "status": "unavailable_after_cleanup",
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "mime_type": None,
        "source_session_id": session_id,
        "capture_source": None,
        "direct_upload_status": "not_provided",
    }

    entries = _file_registry_entries_for(file_registry, session_id)
    if entries:
        picked = _pick_original_image_entry(entries)
        if picked is not None:
            _, entry = picked
            attached = _copy_original_image_path(
                ticket_dir,
                Path(entry["path"]),
                session_id,
                capture_source="file_registry",
            )
            if attached is not None:
                return attached

    image_path = _session_image_path_for(session_store, session_id)
    if image_path:
        attached = _try_session_image_path_fallback(ticket_dir, image_path, session_id)
        if attached is not None:
            return attached

    return unavailable


def _copy_original_image_path(
    ticket_dir: Path,
    src_path: Path,
    session_id: str | None,
    *,
    capture_source: str,
) -> dict[str, Any] | None:
    suffix = src_path.suffix.lower() or ".png"
    if suffix not in _IMAGE_EXTENSIONS:
        return None
    if not src_path.is_file():
        return None
    dst = ticket_dir / f"original{suffix}"
    try:
        shutil.copy2(src_path, dst)
        size = dst.stat().st_size
        sha = file_sha256(dst)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError) and not src_path.is_file():
            return None
        try:
            dst.unlink()
        except OSError:
            pass
        return _failed_original_image(
            session_id,
            type(exc).__name__,
            "Original image could not be saved.",
        )
    return {
        "status": "attached",
        "filename": dst.name,
        "sha256": sha,
        "size_bytes": size,
        "mime_type": guess_mime(dst),
        "source_session_id": session_id,
        "capture_source": capture_source,
        "direct_upload_status": "not_provided",
    }


def _session_image_path_for(session_store, session_id: str | None) -> str | None:
    if session_store is None or not session_id:
        return None
    try:
        session_data = session_store.get(session_id)
    except Exception:
        return None
    if not isinstance(session_data, dict):
        return None
    image_path = session_data.get("image_path")
    return image_path if isinstance(image_path, str) else None


def _try_session_image_path_fallback(
    ticket_dir: Path,
    image_path: str,
    session_id: str | None,
) -> dict[str, Any] | None:
    if not image_path or not image_path.strip():
        return None
    src = Path(image_path)
    if not src.is_file():
        return None
    suffix = src.suffix.lower()
    if suffix not in _IMAGE_EXTENSIONS:
        return None
    allowed_root = Path(TEMP_DIR).resolve()
    try:
        src.resolve().relative_to(allowed_root)
    except ValueError:
        return None
    return _copy_original_image_path(
        ticket_dir,
        src,
        session_id,
        capture_source="session_store",
    )


def _collect_final_artifact(
    ticket_dir: Path,
    file_registry,
    session_id: str | None,
    artifact_type: str | None,
    *,
    download_url: str | None = None,
) -> dict[str, Any]:
    """Build the ``final_artifact`` attachment dict.

    First attempts the exact ``download_url`` file id because it represents
    the artifact the user is currently offered for download. If that fails
    (e.g. the URL is invalid, expired, private, or not a final artifact), it
    falls back to FileRegistry by ``session_id``. The client context may still
    contain a historical ``disk_path`` value, but a client-supplied server path
    is not an authorization source for copying files.

    优先按 ``download_url`` 精确解析文件 id，因为它代表用户当前看到的下载产物。
    如果失败（例如 URL 无效、已过期、私有或不是最终产物），再通过
    FileRegistry（按 session_id）查找。客户端上下文里可能仍带旧版 ``disk_path``，
    但客户端提交的服务器磁盘路径不能作为复制附件的授权依据。
    """
    base = {
        "status": "not_applicable",
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "artifact_type": artifact_type,
        "source_session_id": session_id,
        "generated_at": None,
        "history_count": 0,
    }
    if not session_id and not download_url:
        return base

    # --- Primary path: exact /api/files/<id> from frontend ref ---
    if download_url:
        attached = _collect_final_artifact_from_download_url(
            ticket_dir, file_registry, download_url, artifact_type, session_id,
        )
        if attached is not None:
            return attached

    # --- Fallback: FileRegistry lookup by session_id ---
    if session_id:
        entries = _file_registry_entries_for(file_registry, session_id)
        if entries:
            fid, entry, history_count = _pick_final_artifact_entry(entries)
            if fid:
                src_path = Path(entry["path"])
                if src_path.is_file():
                    suffix = src_path.suffix.lower() or ".3mf"
                    dst = ticket_dir / f"final{suffix}"
                    try:
                        shutil.copy2(src_path, dst)
                        size = dst.stat().st_size
                        sha = file_sha256(dst)
                    except OSError as exc:
                        try:
                            dst.unlink()
                        except OSError:
                            pass
                        return _failed_final_artifact(
                            session_id,
                            artifact_type,
                            type(exc).__name__,
                            "Final artifact could not be saved.",
                            history_count=history_count,
                        )
                    else:
                        return {
                            "status": "attached",
                            "filename": dst.name,
                            "sha256": sha,
                            "size_bytes": size,
                            "artifact_type": suffix.lstrip(".") or artifact_type,
                            "source_session_id": session_id,
                            "generated_at": _format_created_at(entry.get("created_at")),
                            "history_count": history_count,
                        }

    # Neither registry nor fallback yielded a file.
    return {**base, "status": "expired_ttl"}


def _collect_lut(ticket_dir: Path, context: dict[str, Any]) -> dict[str, Any]:
    """Build the ``lut`` attachment dict."""
    base = _empty_lut_attachment()
    if context.get("source_version") == "material":
        return base
    if context.get("source_version") == "native":
        return base
    lut_names = _lut_names_from_context(context)
    if not lut_names:
        return base

    items = [
        _collect_single_lut(
            ticket_dir,
            lut_name,
            filename_prefix="lut" if len(lut_names) == 1 else f"lut_{index}",
        )
        for index, lut_name in enumerate(lut_names, start=1)
    ]
    if len(items) == 1:
        return items[0]

    aggregate = {
        **base,
        "status": "attached" if all(item.get("status") in {"attached", "preset_reference_only"} for item in items) else "partial",
        "kind": "multiple",
        "name": lut_names[0],
        "names": lut_names,
        "items": items,
    }
    failed = [
        item
        for item in items
        if item.get("status") not in {"attached", "preset_reference_only"}
    ]
    if failed:
        aggregate["error_type"] = "PartialLutCollection"
        aggregate["error_message"] = "One or more LUTs could not be saved."
    return aggregate


def _collect_single_lut(
    ticket_dir: Path,
    lut_name: str,
    *,
    filename_prefix: str,
) -> dict[str, Any]:
    """Collect one legacy LUT attachment or preset reference.

    收集一个传统 LUT 附件或预设引用。
    """

    if not _is_lut_name_path_safe(lut_name):
        return _failed_lut(
            str(lut_name),
            None,
            "InvalidLutName",
            "LUT could not be saved.",
        )

    found = _find_lut_file(lut_name)
    if found is None:
        return {
            **_empty_lut_attachment(),
            "status": "unavailable",
            "name": lut_name,
        }

    # Classify custom vs preset. Custom LUTs typically live under
    # lut-preset/Custom/ or have names starting with "Custom".
    is_custom = lut_name.lower().startswith("custom")
    if not is_custom:
        try:
            rel_parent = found.parent.relative_to(REPO_ROOT / "lut-preset")
            # Any path segment that includes ``custom`` treats this as a
            # custom-authored LUT (case-insensitive so "Custom"/"custom"
            # sub-folders both match).
            # 路径段含有 ``custom`` 的都视为自定义。
            is_custom = any(
                "custom" in part.lower() for part in rel_parent.parts
            )
        except ValueError:
            is_custom = False
    try:
        size = found.stat().st_size
        sha = file_sha256(found)
    except OSError as exc:
        return _failed_lut(
            lut_name,
            "custom" if is_custom else "preset",
            type(exc).__name__,
            "LUT could not be saved.",
        )
    if is_custom:
        suffix = found.suffix.lower()
        dst = ticket_dir / f"{filename_prefix}{suffix}"
        try:
            shutil.copy2(found, dst)
        except OSError as exc:
            try:
                dst.unlink()
            except OSError:
                pass
            return _failed_lut(
                lut_name,
                "custom",
                type(exc).__name__,
                "LUT could not be saved.",
            )
        return {
            "status": "attached",
            "kind": "custom",
            "name": lut_name,
            "preset_relative_path": None,
            "filename": dst.name,
            "sha256": sha,
            "size_bytes": size,
            "metadata": {},
        }
    try:
        logical_path = found.relative_to(_safe_lut_preset_root()).as_posix()
    except ValueError:
        logical_path = LUTManager.logical_lut_path(found)
    if logical_path is None:
        return _failed_lut(
            lut_name, "preset", "InvalidAttachmentManifest",
            "LUT reference is outside configured roots.",
        )
    rel = f"lut-preset/{logical_path}"
    return {
        "status": "preset_reference_only",
        "kind": "preset",
        "name": lut_name,
        "preset_relative_path": rel,
        "filename": None,
        "sha256": sha,
        "size_bytes": size,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Async finalization
# ---------------------------------------------------------------------------


def _attachment_file_path(
    ticket_dir: Path,
    attachment: dict[str, Any],
    *,
    failure_message: str,
) -> Path | None:
    filename = attachment.get("filename")
    if _is_non_empty_string(filename):
        filename_str = str(filename)
        is_plain_name = (
            filename_str == Path(filename_str).name
            and filename_str == PureWindowsPath(filename_str).name
        )
        candidate = ticket_dir / filename_str
        if is_plain_name and candidate.is_file():
            return candidate
    attachment.update(
        {
            "status": "failed",
            "sha256": None,
            "size_bytes": None,
            "error_type": "AttachmentFileMissing",
            "error_message": failure_message,
        }
    )
    return None


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _safe_preset_relative_path(value: Any) -> bool:
    if not _is_non_empty_string(value):
        return False
    path_text = str(value)
    if "\\" in path_text:
        return False
    try:
        posix_path = PurePath(path_text)
        windows_path = PureWindowsPath(path_text)
    except TypeError:
        return False
    if posix_path.is_absolute() or windows_path.is_absolute():
        return False
    if not posix_path.parts or posix_path.parts[0] != "lut-preset":
        return False
    if ".." in (*posix_path.parts, *windows_path.parts):
        return False
    return posix_path.suffix.lower() in _LUT_EXTENSIONS


def _mark_invalid_attachment_manifest(
    attachment: dict[str, Any],
) -> bool:
    attachment.update(
        {
            "status": "failed",
            "filename": None,
            "sha256": None,
            "size_bytes": None,
            "error_type": "InvalidAttachmentManifest",
            "error_message": "Attachment manifest is invalid.",
        }
    )
    return False


def _attachment_metadata_is_valid(
    attachment: dict[str, Any],
    *,
    required_text_fields: tuple[str, ...],
    path: Path | None = None,
) -> bool:
    if not _is_sha256_hex(attachment.get("sha256")):
        return _mark_invalid_attachment_manifest(attachment)
    if not _is_positive_int(attachment.get("size_bytes")):
        return _mark_invalid_attachment_manifest(attachment)
    if any(
        not _is_non_empty_string(attachment.get(field))
        for field in required_text_fields
    ):
        return _mark_invalid_attachment_manifest(attachment)
    if path is not None:
        try:
            if attachment.get("size_bytes") != path.stat().st_size:
                return _mark_invalid_attachment_manifest(attachment)
            if str(attachment.get("sha256")).lower() != file_sha256(path).lower():
                return _mark_invalid_attachment_manifest(attachment)
        except OSError:
            return _mark_invalid_attachment_manifest(attachment)
    return True


def _preset_lut_manifest_is_valid(attachment: dict[str, Any]) -> bool:
    if attachment.get("kind") != "preset":
        return _mark_invalid_attachment_manifest(attachment)
    if not _is_non_empty_string(attachment.get("name")):
        return _mark_invalid_attachment_manifest(attachment)
    if not _safe_preset_relative_path(attachment.get("preset_relative_path")):
        return _mark_invalid_attachment_manifest(attachment)
    relative_parts = PurePath(str(attachment["preset_relative_path"])).parts[1:]
    try:
        if relative_parts and relative_parts[0] == "Cloud":
            root = LUTManager.cloud_lut_dir().resolve()
            relative_parts = relative_parts[1:]
        else:
            root = _safe_lut_preset_root()
        preset_path = _lut_file_within_root(root.joinpath(*relative_parts), root)
    except (OSError, ValueError):
        return _mark_invalid_attachment_manifest(attachment)
    if preset_path is None:
        return _mark_invalid_attachment_manifest(attachment)
    return _attachment_metadata_is_valid(
        attachment,
        required_text_fields=(),
        path=preset_path,
    )


def _final_artifact_type_matches_filename(attachment: dict[str, Any]) -> bool:
    artifact_type = attachment.get("artifact_type")
    filename = attachment.get("filename")
    if not _is_non_empty_string(artifact_type) or not _is_non_empty_string(filename):
        return _mark_invalid_attachment_manifest(attachment)
    suffix = Path(str(filename)).suffix.lower().lstrip(".")
    if suffix not in {"3mf", "zip"} or artifact_type != suffix:
        return _mark_invalid_attachment_manifest(attachment)
    return True


def _original_image_manifest_matches_file(
    attachment: dict[str, Any],
    path: Path,
) -> bool:
    if path.suffix.lower() not in _IMAGE_EXTENSIONS:
        return _mark_invalid_attachment_manifest(attachment)
    if attachment.get("mime_type") != guess_mime(path):
        return _mark_invalid_attachment_manifest(attachment)
    return True


def _attached_lut_manifest_matches_file(
    attachment: dict[str, Any],
    path: Path,
) -> bool:
    if attachment.get("kind") != "custom":
        return _mark_invalid_attachment_manifest(attachment)
    if path.suffix.lower() not in _LUT_EXTENSIONS:
        return _mark_invalid_attachment_manifest(attachment)
    return True


def _lut_attachment_is_complete(
    ticket_dir: Path,
    attachment: dict[str, Any],
) -> bool:
    """Validate a collected LUT attachment item.

    校验已收集的单个 LUT 附件条目。
    """

    if attachment.get("status") == "preset_reference_only":
        return _preset_lut_manifest_is_valid(attachment)
    if attachment.get("status") != "attached":
        return False
    lut_path = _attachment_file_path(
        ticket_dir,
        attachment,
        failure_message="LUT is missing from the ticket directory.",
    )
    if lut_path is None:
        return False
    if not _attached_lut_manifest_matches_file(attachment, lut_path):
        return False
    return _attachment_metadata_is_valid(
        attachment,
        required_text_fields=("kind", "name"),
        path=lut_path,
    )


def _attachment_section(
    attachments: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    value = attachments.get(key)
    if isinstance(value, dict):
        return value
    replacement: dict[str, Any] = {
        "status": "failed",
        "filename": None,
        "error_type": "InvalidAttachmentManifest",
        "error_message": "Attachment manifest is invalid.",
    }
    attachments[key] = replacement
    return replacement


def _critical_sync_attachments_complete(
    payload: dict[str, Any],
    ticket_dir: Path,
) -> bool:
    raw_context = payload.get("context")
    context = raw_context if isinstance(raw_context, dict) else {}
    raw_attachments = payload.get("attachments")
    if isinstance(raw_attachments, dict):
        attachments = raw_attachments
    else:
        attachments = {}
        payload["attachments"] = attachments
    complete = True

    if _original_image_expected(context):
        original = _attachment_section(attachments, "original_image")
        if original.get("status") != "attached":
            complete = False
        else:
            original_path = _attachment_file_path(
                ticket_dir,
                original,
                failure_message="Original image is missing from the ticket directory.",
            )
            if original_path is None:
                complete = False
            elif not _original_image_manifest_matches_file(original, original_path):
                complete = False
            elif not _attachment_metadata_is_valid(
                original,
                required_text_fields=("mime_type",),
                path=original_path,
            ):
                complete = False

    if _final_artifact_expected(context):
        final = _attachment_section(attachments, "final_artifact")
        if final.get("status") != "attached":
            complete = False
        else:
            final_path = _attachment_file_path(
                ticket_dir,
                final,
                failure_message="Final artifact is missing from the ticket directory.",
            )
            if final_path is None:
                complete = False
            elif not _final_artifact_type_matches_filename(final):
                complete = False
            elif not _attachment_metadata_is_valid(
                final,
                required_text_fields=("artifact_type",),
                path=final_path,
            ):
                complete = False

    if _lut_critical_for_finalize(context):
        lut = _attachment_section(attachments, "lut")
        raw_items = lut.get("items")
        if isinstance(raw_items, list) and raw_items:
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    complete = False
                    continue
                if not _lut_attachment_is_complete(ticket_dir, raw_item):
                    complete = False
        elif not _lut_attachment_is_complete(ticket_dir, lut):
            complete = False

    return complete


_TICKET_LOCKS: dict[str, asyncio.Lock] = {}


def _ticket_lock(ticket_id: str) -> asyncio.Lock:
    """Serialize uploads and ``ticket.json`` rewrites for one ticket.

    串行化同一工单的上传与 ``ticket.json`` 回写，避免重复上传。
    """
    return _TICKET_LOCKS.setdefault(ticket_id, asyncio.Lock())


def _write_ticket_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def resubmit_ticket_async(ticket_dir: Path) -> dict[str, Any]:
    """Retry uploading an assembled ticket unless it already succeeded.

    重新上传已装配的工单；已成功上传的工单直接返回当前状态。

    Args:
        ticket_dir: Local ticket directory. / 本地工单目录。

    Returns:
        dict[str, Any]: Updated ticket payload. / 更新后的工单内容。
    """
    ticket_json_path = ticket_dir / "ticket.json"
    async with _ticket_lock(ticket_dir.name):
        payload = json.loads(ticket_json_path.read_text(encoding="utf-8"))
        submission = payload.get("submission")
        status = submission.get("status") if isinstance(submission, dict) else None
        if status in ("submitted", "pending") or payload.get("assembly_status") == "in_progress":
            return payload
        payload["submission"] = await submit_ticket_directory(ticket_dir, payload)
        _write_ticket_json(ticket_json_path, payload)
        return payload


async def finalize_ticket_async(
    ticket_dir: Path,
    file_registry,
    session_store=None,
) -> None:
    """Background task: materials zip + index / summary + server upload.

    后台任务：打包耗材 zip、渲染 index/summary、上传到官方反馈服务；任一子步骤失败
    整体降级为 ``partial_failed``，不终止流程。

    ``session_store`` is currently unused; it is accepted so the task signature
    can grow to include session-aware cleanup without forcing callers to
    rebuild ``background_tasks.add_task(...)`` argument lists across the
    codebase.
    """
    del session_store
    try:
        ticket_json_path = ticket_dir / "ticket.json"
        if not ticket_json_path.exists():
            return
        payload = json.loads(ticket_json_path.read_text(encoding="utf-8"))
        ticket_id = payload.get("ticket_id", "<unknown>")
        log.info(
            "Assembly started.",
            extra={
                "event": "feedback_ticket_assembled_init",
                "ticket_id": ticket_id,
            },
        )
        partial = False
        raw_context = payload.get("context")
        context = raw_context if isinstance(raw_context, dict) else {}
        if context is not raw_context:
            payload["context"] = context
        raw_attachments = payload.get("attachments")
        if isinstance(raw_attachments, dict):
            attachments = raw_attachments
        else:
            attachments = {}
            payload["attachments"] = attachments

        # --- Materials zip ---
        if (
            context.get("source_version") == "material"
            and context.get("selected_material_dir_names")
        ):
            try:
                materials_root = REPO_ROOT / "materials"
                bundle = pack_materials(
                    materials_root,
                    list(context["selected_material_dir_names"]),
                    ticket_dir / "materials.zip",
                    timeout_s=materials_bundle_timeout_s(),
                )
                attachments["materials_bundle"] = {
                    "status": bundle.status,
                    "filename": bundle.path.name if bundle.path else None,
                    "sha256": bundle.sha256,
                    "compressed_size_bytes": bundle.compressed_size_bytes,
                    "entry_count": bundle.entry_count,
                    "included_dirs": bundle.included_dirs,
                    "excluded_cache_keys": bundle.excluded_cache_keys,
                }
                if bundle.status == "attached":
                    log.info(
                        "Materials bundle packed.",
                        extra={
                            "event": "feedback_materials_bundle_packed_done",
                            "ticket_id": ticket_id,
                            "entry_count": bundle.entry_count,
                        },
                    )
                else:
                    partial = True
                    log.error(
                        "Materials bundle not attached.",
                        extra={
                            "event": "feedback_materials_bundle_packed_failed",
                            "ticket_id": ticket_id,
                            "error_type": "MaterialsBundleNotAttached",
                            "error_message": f"status={bundle.status}",
                        },
                    )
            except Exception as exc:
                partial = True
                log.error(
                    "Materials bundle packing crashed.",
                    extra={
                        "event": "feedback_materials_bundle_packed_failed",
                        "ticket_id": ticket_id,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )

        if not _critical_sync_attachments_complete(payload, ticket_dir):
            partial = True

        # --- Index + summary ---
        try:
            index_md = generate_index_markdown(ticket_id, ticket_dir, payload)
            summary_txt = generate_summary_text(ticket_id, payload)
            (ticket_dir / "index.md").write_text(index_md, encoding="utf-8")
            (ticket_dir / "summary.txt").write_text(summary_txt, encoding="utf-8")
        except Exception as exc:
            partial = True
            log.error(
                "Index / summary render failed.",
                extra={
                    "event": "feedback_ticket_assembled_failed",
                    "ticket_id": ticket_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )

        # --- Finalize status, then upload ---
        #
        # A failed upload is not a partial assembly: the local ticket stays
        # complete and the user can retry from the dialog. The assembly status
        # is fixed before uploading so retries send an identical ticket.
        # 上传失败不算装配不完整：本地工单仍然完整，用户可在对话框重试。
        # 先确定装配状态再上传，保证重试时发送的工单内容完全一致。
        payload["assembly_status"] = "partial_failed" if partial else "done"
        payload["submission"] = {"status": "pending"}
        _write_ticket_json(ticket_json_path, payload)
        async with _ticket_lock(ticket_id):
            payload["submission"] = await submit_ticket_directory(ticket_dir, payload)
            _write_ticket_json(ticket_json_path, payload)
        log.info(
            "Assembly finished.",
            extra={
                "event": "feedback_ticket_assembled_done",
                "ticket_id": ticket_id,
                "partial": partial,
                "submission_status": payload["submission"]["status"],
            },
        )
    except Exception as exc:
        log.error(
            "finalize_ticket_async crashed.",
            extra={
                "event": "feedback_ticket_assembled_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )


# ---------------------------------------------------------------------------
# Startup cleanup
# ---------------------------------------------------------------------------


def _iter_ticket_dirs(feedback_root: Path) -> Iterable[Path]:
    """Yield every ``LUM-*`` directory under ``feedback_root/<YYYY-MM>/``."""
    if not feedback_root.is_dir():
        return
    for month_dir in feedback_root.iterdir():
        if not month_dir.is_dir():
            continue
        for ticket_dir in month_dir.iterdir():
            if not ticket_dir.is_dir():
                continue
            if not ticket_dir.name.startswith("LUM-"):
                continue
            yield ticket_dir


def _parse_received_cst(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def run_startup_cleanup(
    feedback_root: Path,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Trim old attachments + mark interrupted tickets at app startup.

    启动时清理旧附件、把异常残留的 in_progress 工单标记为 interrupted。

    Returns:
        dict[str, int]: Counters ``{"interrupted": N, "pruned": N}`` where
            ``interrupted`` is the number of tickets whose assembly_status
            was flipped to ``interrupted`` this pass, and ``pruned`` is the
            number of tickets from which bulky attachments were removed.
    """
    counters = {"interrupted": 0, "pruned": 0}
    if os.environ.get("LUMINA_FEEDBACK_STARTUP_CLEANUP", "").lower() == "false":
        return counters
    if not feedback_root.is_dir():
        return counters

    current = now if now is not None else now_beijing()
    try:
        ttl_days = ticket_attachment_ttl_days()
    except Exception:
        ttl_days = 30
    attachment_cutoff = current - timedelta(days=ttl_days)
    interrupted_cutoff = current - timedelta(
        minutes=_STARTUP_INTERRUPTED_AFTER_MINUTES,
    )

    for ticket_dir in _iter_ticket_dirs(feedback_root):
        try:
            ticket_json = ticket_dir / "ticket.json"
            if not ticket_json.exists():
                continue
            try:
                payload = json.loads(ticket_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            received = _parse_received_cst(payload.get("received_at_cst"))
            if received is None:
                continue
            mutated = False

            # Interrupted detection first so the tag is visible even if the
            # ticket is also old enough to lose its attachments.
            status = payload.get("assembly_status")
            if status in ("pending", "in_progress") and received < interrupted_cutoff:
                payload["assembly_status"] = "interrupted"
                mutated = True
                counters["interrupted"] += 1
                log.warning(
                    "Ticket assembly interrupted; marking for follow-up.",
                    extra={
                        "event": "feedback_ticket_assembly_interrupted",
                        "ticket_id": payload.get("ticket_id"),
                        "error_type": "AssemblyInterrupted",
                        "error_message": (
                            "ticket.assembly_status was still pending/"
                            "in_progress past the grace window"
                        ),
                        "path": str(ticket_dir),
                    },
                )

            submission = payload.get("submission")
            if (
                isinstance(submission, dict)
                and submission.get("status") == "pending"
                and received < interrupted_cutoff
            ):
                submission.update(status="failed", error_type="UploadInterrupted")
                mutated = True

            # Attachment TTL cleanup.
            if received < attachment_cutoff:
                removed_any = False
                for glob in _BULKY_ATTACHMENT_GLOBS:
                    for file in ticket_dir.glob(glob):
                        try:
                            file.unlink()
                            removed_any = True
                        except OSError:
                            continue
                if removed_any:
                    counters["pruned"] += 1

            if mutated:
                ticket_json.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except Exception as exc:
            log.error(
                "Startup cleanup failed for ticket.",
                extra={
                    "event": "feedback_startup_cleanup_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "path": str(ticket_dir),
                },
            )
    return counters
