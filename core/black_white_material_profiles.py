"""Publish black/white models as normal material-library profiles.
将黑白耗材模型发布为常规耗材库档案。
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from core import lumina_box_archive as archive
from core.backed_gradient_archive import save_backed_gradient_material_archive
from core.backed_gradient_backing_store import _prepare_backing_material_result, _write_backing_material_results
from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID
from core.backed_gradient_store import BackedGradientStore
from core.errors import MaterialArchiveConflictError


def black_white_archive_index(root: Path) -> dict[str, tuple[Path, dict]]:
    """Locate black/white profiles by stable identity. / 按稳定身份查找黑白耗材档案。

    Args:
        root: Material-library root.（耗材库目录。）
    Returns:
        Identity to archive path and metadata.（身份对应的路径及资料。）
    """
    result = {}
    for path in root.rglob("material.json"):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        main = archive._load_archive_payload(path)
        if main and main.get("backing_material_id"):
            result[main["backing_material_id"]] = (path.parent, main)
    return result


def publish_black_white_profiles(store: BackedGradientStore, entries: list[tuple[dict, dict | None]]) -> list[dict]:
    """Publish models and ordinary archives together, restoring files on failure.
    同步发布模型与常规档案，失败时恢复文件。

    Args:
        store: Capture and library storage.（采集及耗材库。）
        entries: Frozen captures and their fitted models.（冻结采集及拟合模型。）
    Returns:
        Published backing records.（已发布黑白耗材记录。）
    """
    from core.backed_gradient_backing_transfer import collect_backing_documents
    from core.backed_gradient_backing_store import get_backing_material
    from core.single_stage import invalidate_material_library_cache

    documents = [_prepare_backing_material_result(store, snapshot, fitted) for snapshot, fitted in entries]
    ready = [document for document in documents if document["status"] == "ready"]
    with archive._ARCHIVE_WRITE_LOCK, TemporaryDirectory(prefix=".black-white-publication-", dir=store.root) as temporary:
        staging = Path("\\\\?\\" + str(Path(temporary).resolve())) if os.name == "nt" else Path(temporary)
        index = black_white_archive_index(store.root)
        destinations = []
        for document in ready:
            snapshot, fit = deepcopy(document["snapshot"]), deepcopy(document["fit"])
            fit.update(optical_model_id=SPECTRAL_SMOOTH_MODEL_ID, material_symbol=document["role"],
                       status="complete", **{key: snapshot[key] for key in ("dataset_id", "dataset_revision", "input_hash")})
            snapshot.update(material_symbol=document["role"], backing_material_id=document["material_id"])
            if snapshot.get("opposite_version_id"):
                snapshot["backing_documents"] = [get_backing_material(store, snapshot["opposite_material_id"],
                                                                       version_id=snapshot["opposite_version_id"])]
            snapshot["backing_documents"] = [*snapshot.get("backing_documents", []), *ready]
            frozen = collect_backing_documents(store, [snapshot], require_complete=True)
            snapshot["backing_documents"] = list({item["version_id"]: item for item in [*frozen, *ready]}.values())
            previous = index.get(document["material_id"])
            identity = {"name": document["name"], "brand": document["brand"], "material_type": document["material_type"]}
            if previous:
                relative = previous[0].relative_to(store.root)
                shutil.copytree(previous[0], staging / "materials" / relative)
                identity.update(name=previous[1]["material_name"], brand=previous[1].get("brand", ""),
                                material_type=previous[1].get("material_type", ""))
            saved = save_backed_gradient_material_archive(
                material_name=identity["name"], brand=identity["brand"], material_type=identity["material_type"],
                notes=snapshot.get("notes", ""), measurement_payload=snapshot, fit_payload=fit,
                overwrite=bool(previous), materials_dir=str(staging / "materials"))
            relative = Path(saved.archive_path).parent.relative_to(staging / "materials")
            if not previous and (store.root / relative).exists():
                raise MaterialArchiveConflictError("A material with this brand and name already exists. Use its library record.")
            if relative in destinations:
                raise MaterialArchiveConflictError("Black and white materials need different archive identities.")
            destinations.append(relative)
        swapped = []
        try:
            with store._connection(write=True) as connection:
                saved_documents = _write_backing_material_results(connection, documents)
                for relative in destinations:
                    target, backup = store.root / relative, staging / "originals" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(target, backup)
                    swapped.append(relative)
                    os.replace(staging / "materials" / relative, target)
        except BaseException:
            for relative in reversed(swapped):
                target, backup = store.root / relative, staging / "originals" / relative
                if target.exists():
                    shutil.rmtree(target)
                if backup.exists():
                    os.replace(backup, target)
            raise
    invalidate_material_library_cache(str(store.root))
    return saved_documents
