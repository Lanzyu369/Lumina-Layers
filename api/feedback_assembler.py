"""Ticket directory assembly for the reproducible bug-report pipeline.

反馈工单目录装配：同步部分（原图 / 生成产物 / LUT）+ 异步部分（耗材 zip、
index.md、summary.txt、邮件发送）+ 启动时清理。

Design (`.kiro/specs/reproducible-bug-reports/design.md` §Components §5):

* Sync path ``collect_sync_attachments`` runs inside the HTTP handler so the
  response waits only on small file copies + sha256 (bounded to ~2 s).
* Async path ``finalize_ticket_async`` runs via FastAPI BackgroundTasks; it
  packs ``materials.zip``, renders ``index.md`` / ``summary.txt``, and
  sends the bug-report email. All steps are independently try/except so a
  single failure downgrades the ticket to ``assembly_status='partial_failed'``
  but never crashes the background worker pool.
* ``run_startup_cleanup`` purges bulky attachments that outlived their TTL
  and marks abandoned in-flight tickets as ``interrupted``.

同步装配只做小文件拷贝与指纹（HTTP 请求内 ≤2 秒），其余大头（耗材 zip、
渲染索引、发邮件）放后台任务。启动时清理按 TTL 删除大附件，并把异常残留
的装配中工单标为 interrupted。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from api.feedback_config import (
    materials_bundle_timeout_s,
    ticket_attachment_ttl_days,
)
from api.feedback_fingerprint import file_sha256, guess_mime
from api.feedback_index import generate_index_markdown, generate_summary_text
from api.feedback_materials_bundle import pack_materials
from api.feedback_time import now_beijing
from api.structured_logging import get_logger
from config import TEMP_DIR

__all__ = [
    "SyncCollectionResult",
    "collect_sync_attachments",
    "finalize_ticket_async",
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

_IMAGE_EXTENSIONS = frozenset(
    (".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"),
)
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
    except Exception:
        return None
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
    except Exception:
        return None
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
    except OSError:
        return None
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
    """Locate a preset/custom LUT by stem under ``lut-preset/``.

    先精确匹配，再大小写不敏感；按 .npy/.json/.npz/.msgpack 的优先顺序取。
    """
    if not lut_name:
        return None
    lut_preset_dir = REPO_ROOT / "lut-preset"
    if not lut_preset_dir.is_dir():
        return None
    for ext in _LUT_EXTENSIONS:
        exact = lut_preset_dir / f"{lut_name}{ext}"
        if exact.exists():
            return exact
    # Case-insensitive fallback: search children.
    try:
        lowered = lut_name.lower()
        for path in lut_preset_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.stem.lower() != lowered:
                continue
            if path.suffix.lower() in _LUT_EXTENSIONS:
                return path
    except OSError:
        return None
    return None


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
    context = payload.get("context") or {}

    # Defaults used when a sub-step bails early.
    default_original = {
        "status": "not_applicable",
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "mime_type": None,
        "source_session_id": None,
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
        original = _collect_original_image(
            ticket_dir, file_registry, session_id, session_store=session_store,
        )
        log.info(
            "Attachment collected.",
            extra={
                "event": "feedback_attachment_collected",
                "attachment_kind": "original_image",
                "status": original["status"],
                "ticket_id": ticket_id,
            },
        )
    except Exception as exc:
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
    }

    entries = _file_registry_entries_for(file_registry, session_id)
    if entries:
        picked = _pick_original_image_entry(entries)
        if picked is not None:
            _, entry = picked
            attached = _copy_original_image_path(
                ticket_dir, Path(entry["path"]), session_id,
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
) -> dict[str, Any] | None:
    suffix = src_path.suffix.lower() or ".png"
    if suffix not in _IMAGE_EXTENSIONS:
        return None
    dst = ticket_dir / f"original{suffix}"
    try:
        shutil.copy2(src_path, dst)
        size = dst.stat().st_size
        sha = file_sha256(dst)
    except OSError:
        return None
    return {
        "status": "attached",
        "filename": dst.name,
        "sha256": sha,
        "size_bytes": size,
        "mime_type": guess_mime(dst),
        "source_session_id": session_id,
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
    return _copy_original_image_path(ticket_dir, src, session_id)


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
                    except OSError:
                        try:
                            dst.unlink()
                        except OSError:
                            pass
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
    base = {
        "status": "not_applicable",
        "kind": None,
        "name": None,
        "preset_relative_path": None,
        "filename": None,
        "sha256": None,
        "size_bytes": None,
        "metadata": {},
    }
    if context.get("source_version") == "material":
        return base
    lut_name = context.get("lut_name")
    if not lut_name:
        return base

    found = _find_lut_file(lut_name)
    if found is None:
        return base

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
    size = found.stat().st_size
    sha = file_sha256(found)
    if is_custom:
        suffix = found.suffix.lower()
        dst = ticket_dir / f"lut{suffix}"
        shutil.copy2(found, dst)
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
        rel = found.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        rel = str(found)
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


async def finalize_ticket_async(
    ticket_dir: Path,
    file_registry,
    session_store=None,
) -> None:
    """Background task: materials zip + index / summary + email.

    后台任务：打包耗材 zip、渲染 index/summary、发送邮件；任一子步骤失败
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
        context = payload.get("context") or {}
        attachments = payload.setdefault("attachments", {})

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

        # --- Email ---
        #
        # Note on the ``partial`` flag: a failed email send is intentionally
        # NOT treated as a partial assembly failure. Email is a separate
        # delivery channel; the ticket directory and all attachments can be
        # fully populated even when SMTP is unreachable, and operators who
        # pull tickets directly from disk shouldn't see ``partial_failed``
        # just because the mail server timed out. We still record
        # ``email.status='failed'`` and emit an ERROR log so the failure is
        # observable.
        # 邮件失败不翻转 partial_failed：邮件是独立通道，工单目录与所有
        # 附件已完整；SMTP 超时不应让从磁盘直取工单的运维看到误导性的
        # partial_failed。仍保留 email.status='failed' 与 ERROR 日志。
        try:
            from api.feedback_email import (  # noqa: PLC0415
                is_email_configured,
                send_bug_report_email_async,
            )
            if is_email_configured():
                sent = await send_bug_report_email_async(
                    ticket_id=ticket_id,
                    request_payload=payload,
                    dump_path=str(ticket_dir),
                    attachments_dir=ticket_dir,
                )
                payload.setdefault("email", {})["status"] = "sent" if sent else "failed"
            else:
                payload.setdefault("email", {})["status"] = "unconfigured"
        except Exception as exc:
            payload.setdefault("email", {})["status"] = "failed"
            log.error(
                "Email send threw.",
                extra={
                    "event": "feedback_email_failed",
                    "ticket_id": ticket_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "dependency": "aiosmtplib",
                },
            )

        # --- Finalize ticket.json ---
        payload["assembly_status"] = "partial_failed" if partial else "done"
        ticket_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info(
            "Assembly finished.",
            extra={
                "event": "feedback_ticket_assembled_done",
                "ticket_id": ticket_id,
                "partial": partial,
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
