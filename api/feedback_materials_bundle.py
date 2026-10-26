"""Pack a subset of ``materials/`` directories into a zip for bug reports.

反馈工单用的耗材档案打包器：把选中的 ``materials/<dir>/`` 目录打包成 zip。

Design constraints (`.kiro/specs/reproducible-bug-reports/design.md` §5):

* Every file in selected material directories is preserved, including
  ``_solver_cache`` sub-directories needed to reproduce the original state.
* An optional positive ``LUMINA_FEEDBACK_MATERIALS_BUNDLE_TIMEOUT_S`` caps
  packing time; zero disables the timeout. On timeout we delete the partial zip and return
  ``status='packaging_timeout'`` so the assembler can continue with other
  attachments instead of failing the whole ticket.
* The function never raises for recoverable issues (missing dir, empty
  selection). It raises ``PackagingTimeoutError`` internally but catches it
  itself before returning.

设计约束：所选耗材目录的全部文件都会保留，包括 ``_solver_cache``；超时
后删除部分 zip 并返回 ``packaging_timeout`` 状态，让工单装配流程继续处理
其他附件。
"""

from __future__ import annotations

import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from api.structured_logging import get_logger

__all__ = [
    "MaterialsBundleResult",
    "PackagingTimeoutError",
    "pack_materials",
]


log = get_logger(__name__)


class PackagingTimeoutError(Exception):
    """Raised internally when the zip packing loop exceeds its wall-clock budget.

    当打包循环超过墙钟超时时内部抛出；由 :func:`pack_materials` 自行捕获。
    """


@dataclass(frozen=True)
class MaterialsBundleResult:
    """Outcome of a :func:`pack_materials` call.

    :func:`pack_materials` 的返回结果。

    Attributes:
        status: Terminal status — ``attached`` means the zip is on disk and
            its entries are ready; ``packaging_timeout`` means we gave up
            and deleted the partial zip; ``not_applicable`` means no
            selection was provided.
            (终态状态：attached 表示 zip 已落盘且条目可用；packaging_timeout
            表示超时放弃并删除了部分产物；not_applicable 表示未选中任何目录。)
        path: Path to the produced zip or ``None`` when not ``attached``.
            (产物路径；非 attached 时为 None。)
        compressed_size_bytes: Size of the produced zip in bytes.
        entry_count: Number of files written into the zip, including caches.
        included_dirs: Material directory names that contributed at least one
            file to the zip. Directories that were requested but missing on
            disk are NOT listed here.
        excluded_cache_keys: Legacy result field; always empty because caches
            are preserved. / 兼容旧返回结构，缓存不再排除，因此始终为空。
    """

    status: Literal["attached", "packaging_timeout", "not_applicable"]
    path: Path | None
    compressed_size_bytes: int | None
    entry_count: int
    included_dirs: list[str] = field(default_factory=list)
    excluded_cache_keys: list[str] = field(default_factory=list)


def _resolve_material_dir(
    materials_root: Path, dir_name: str,
) -> Path | None:
    """Validate and resolve a material directory name against the root.

    校验并解析耗材目录名，确保不会逃逸到 materials_root 之外。

    Rules:
    1. dir_name must be a non-empty string.
    2. dir_name must not be an absolute path.
    3. dir_name must not contain ``..`` path components.
    4. After resolve(), the result must still be inside materials_root.

    Args:
        materials_root: The resolved materials root directory.
        dir_name: Requested directory name (may be nested like ``Brand/Sub``).

    Returns:
        Path | None: Resolved path if valid, None otherwise.
    """
    if not dir_name or not dir_name.strip():
        return None
    # Reject absolute paths
    if Path(dir_name).is_absolute():
        return None
    # Reject path traversal components
    if ".." in Path(dir_name).parts:
        return None
    candidate = (materials_root / dir_name).resolve()
    materials_root_resolved = materials_root.resolve()
    try:
        candidate.relative_to(materials_root_resolved)
    except ValueError:
        return None
    if not candidate.is_dir():
        return None
    return candidate


def pack_materials(
    materials_root: Path,
    selected_dirs: list[str],
    output_zip: Path,
    timeout_s: int = 0,
    *,
    now_fn=time.monotonic,
) -> MaterialsBundleResult:
    """Pack selected material directories into ``output_zip``.

    将选中的耗材目录打包成 ``output_zip``。

    Args:
        materials_root: Directory containing the per-material sub-directories
            (typically ``<repo>/materials``).
            (存放各耗材子目录的根路径，一般是 ``<repo>/materials``。)
        selected_dirs: Material directory names to include. Empty → no work.
            (需要打包的耗材目录名列表；空时直接返回 not_applicable。)
        output_zip: Destination path for the produced zip.
            (产物 zip 的落盘路径。)
        timeout_s: Wall-clock budget in seconds before the packer bails out
            and deletes the partial zip; zero disables it.
            (墙钟预算，单位秒；零表示不限制打包耗时。)
        now_fn: Monotonic clock hook for tests (defaults to
            :func:`time.monotonic`).
            (测试用单调时钟；默认为 :func:`time.monotonic`。)

    Returns:
        MaterialsBundleResult: Full diagnostic record of the packing run.
    """
    if not selected_dirs:
        return MaterialsBundleResult(
            status="not_applicable",
            path=None,
            compressed_size_bytes=None,
            entry_count=0,
            included_dirs=[],
            excluded_cache_keys=[],
        )

    start = now_fn()
    included_dirs: list[str] = []
    entry_count = 0

    # Pre-validate which requested dirs actually exist so we can log missing
    # ones clearly. Continue packing the rest.
    # 预先筛选出真实存在的目录；缺失的目录单独记录 WARNING 并跳过。
    valid_dirs: list[tuple[str, Path]] = []
    materials_root_resolved = materials_root.resolve()
    for dir_name in selected_dirs:
        resolved = _resolve_material_dir(materials_root, dir_name)
        if resolved is None:
            # Distinguish between invalid path (traversal/absolute) and
            # simply missing directory.
            is_invalid = (
                not dir_name
                or not dir_name.strip()
                or Path(dir_name).is_absolute()
                or ".." in Path(dir_name).parts
            )
            if not is_invalid:
                # Check boundary escape after resolve
                try:
                    candidate = (materials_root / dir_name).resolve()
                    candidate.relative_to(materials_root_resolved)
                except ValueError:
                    is_invalid = True

            if is_invalid:
                log.warning(
                    "Requested material directory name is invalid; skipping.",
                    extra={
                        "event": "feedback_materials_dir_invalid",
                        "error_type": "MaterialDirInvalid",
                        "error_message": (
                            f"dir_name '{dir_name}' is invalid (absolute, "
                            f"traversal, or escapes materials root)"
                        ),
                        "path": str(materials_root),
                        "dir_name": dir_name,
                    },
                )
            else:
                log.warning(
                    "Requested material directory is missing; skipping.",
                    extra={
                        "event": "feedback_materials_dir_missing",
                        "error_type": "MaterialDirMissing",
                        "error_message": (
                            f"materials/{dir_name} does not exist under "
                            f"{materials_root}"
                        ),
                        "path": str(materials_root / dir_name),
                        "dir_name": dir_name,
                    },
                )
            continue
        valid_dirs.append((dir_name, resolved))

    if not valid_dirs:
        return MaterialsBundleResult(
            status="not_applicable",
            path=None,
            compressed_size_bytes=None,
            entry_count=0,
            included_dirs=[],
            excluded_cache_keys=[],
        )

    output_zip.parent.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for dir_name, src_dir in valid_dirs:
                contributed = False
                for path in src_dir.rglob("*"):
                    if path.is_dir():
                        continue
                    # Skip symlinks — they could point outside materials_root.
                    # 跳过符号链接，避免打包外部文件。
                    if path.is_symlink():
                        continue
                    # Verify the resolved file is still inside materials_root.
                    # 确认解析后的文件仍在 materials_root 内。
                    resolved_file = path.resolve()
                    try:
                        resolved_file.relative_to(materials_root_resolved)
                    except ValueError:
                        continue
                    # Compute relative path from materials_root for arcname.
                    try:
                        rel = path.relative_to(materials_root)
                    except ValueError:
                        # Symlink or weird layout escape; skip defensively.
                        continue
                    # Ensure arcname is safe: no absolute path, no .. components.
                    arcname = rel.as_posix()
                    if arcname.startswith("/") or ".." in rel.parts:
                        continue
                    if timeout_s > 0 and (now_fn() - start) >= timeout_s:
                        raise PackagingTimeoutError(
                            f"packing exceeded {timeout_s}s budget"
                        )
                    zf.write(path, arcname=arcname)
                    entry_count += 1
                    contributed = True
                if contributed:
                    included_dirs.append(dir_name)
    except PackagingTimeoutError as exc:
        try:
            output_zip.unlink(missing_ok=True)
        except OSError:
            # Best-effort cleanup of the partial file; ignore removal failure.
            pass
        log.error(
            "Materials bundle packing timed out.",
            extra={
                "event": "feedback_materials_bundle_timeout",
                "error_type": "PackagingTimeoutError",
                "error_message": str(exc),
                "path": str(output_zip),
                "timeout_s": timeout_s,
            },
        )
        return MaterialsBundleResult(
            status="packaging_timeout",
            path=None,
            compressed_size_bytes=None,
            entry_count=0,
            included_dirs=[],
            excluded_cache_keys=[],
        )

    size = output_zip.stat().st_size

    return MaterialsBundleResult(
        status="attached",
        path=output_zip,
        compressed_size_bytes=size,
        entry_count=entry_count,
        included_dirs=included_dirs,
        excluded_cache_keys=[],
    )
