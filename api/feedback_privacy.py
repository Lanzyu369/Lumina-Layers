"""Printer connection redaction for feedback. / 反馈打印机连接信息清理。"""

from __future__ import annotations

from contextlib import ExitStack
from copy import copy
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any
import zipfile
import zlib


def redact_printer_connections(value: Any) -> Any:
    """Copy settings without printer hosts or credentials, including nested fields.

    复制配置并移除打印机地址和凭据（包括嵌套字段），不修改原始配置。

    Args:
        value: Native project settings. 原生项目配置。

    Returns:
        Settings with connection fields removed. 已移除连接字段的配置。
    """
    if isinstance(value, dict):
        return {
            key: redact_printer_connections(item)
            for key, item in value.items()
            if key.casefold() not in {"host_type", "bbl_use_printhost"}
            and not key.casefold().startswith(("print_host", "printhost_"))
        }
    if isinstance(value, list):
        return [redact_printer_connections(item) for item in value]
    return value


def _redact_archive(path: Path) -> bool:
    replacements: dict[str, bytes | Path] = {}
    with ExitStack() as resources:
        scratch = Path(resources.enter_context(tempfile.TemporaryDirectory()))
        with zipfile.ZipFile(path) as source:
            for index, member in enumerate(source.infolist()):
                name = member.filename.casefold()
                suffix = PurePosixPath(name).suffix
                if name.startswith("metadata/") and suffix in {".json", ".config"}:
                    content = source.read(member).decode("utf-8-sig")
                    # Native .config parts can be either JSON settings or XML.
                    if suffix == ".config" and not content.lstrip().startswith(("{", "[")):
                        continue
                    settings = json.loads(content)
                    redacted = redact_printer_connections(settings)
                    if redacted != settings:
                        replacements[member.filename] = json.dumps(
                            redacted, ensure_ascii=False, separators=(",", ":"),
                        ).encode("utf-8")
                elif suffix in {".3mf", ".zip"}:
                    nested = scratch / f"{index}{suffix}"
                    with source.open(member) as reader, nested.open("wb") as writer:
                        shutil.copyfileobj(reader, writer)
                    if _redact_archive(nested):
                        replacements[member.filename] = nested
            if not replacements:
                return False

            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                resources.callback(temporary_path.unlink, missing_ok=True)
                with zipfile.ZipFile(temporary, "w") as destination:
                    destination.comment = source.comment
                    for member in source.infolist():
                        replacement = replacements.get(member.filename)
                        if isinstance(replacement, bytes):
                            destination.writestr(copy(member), replacement)
                        else:
                            reader = (
                                replacement.open("rb") if replacement is not None
                                else source.open(member)
                            )
                            with reader, destination.open(copy(member), "w") as writer:
                                shutil.copyfileobj(reader, writer)
        os.replace(temporary_path, path)
    return True


def copy_feedback_project_artifact(source: Path, destination: Path) -> None:
    """Copy a project or batch ZIP with printer connections removed from metadata.

    为反馈复制项目或批量 ZIP，并移除元数据中的打印机连接信息；源文件不变。
    Archives without connection fields retain their original bytes. Geometry,
    thumbnails, process settings and material settings are preserved.
    无连接信息的归档保持原始字节；模型、缩略图、工艺和材料配置均保留。
    Only a fully inspected copy is published at the attachment path.
    仅在副本完整检查成功后，将其放入正式附件路径。

    Args:
        source: Registry-owned project or ZIP. 注册表持有的项目或 ZIP。
        destination: Feedback-only copy path. 仅用于反馈的副本路径。

    Raises:
        OSError: If copying or replacing the archive fails. 复制或替换归档失败。
        ValueError: If project metadata cannot be inspected. 无法检查项目元数据。
    """
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".project-") as staging:
        prepared = Path(staging) / destination.name
        shutil.copy2(source, prepared)
        try:
            _redact_archive(prepared)
        except (zipfile.BadZipFile, UnicodeDecodeError, RuntimeError, zlib.error) as error:
            raise ValueError("Project metadata could not be prepared for feedback") from error
        os.replace(prepared, destination)
