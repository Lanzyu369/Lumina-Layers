"""Portable immutable backing versions and transactional capture restoration.
可移植的不可变背板版本与事务式采集恢复。
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping, Sequence

from core.backed_gradient_material import BackedGradientComponent, BackedGradientReference
from core.backed_gradient_store import (
    BackedGradientConflictError, BackedGradientNotFoundError, BackedGradientStore,
    _digest, _json, _now, _uuid, _xyz,
)
from core.errors import CoreValidationError

_PUBLICATION_FIELDS = frozenset({"version_id", "updated_at", "active_dataset_id"})


def _immutable(document: Mapping[str, Any]) -> dict:
    return {key: value for key, value in document.items() if key not in _PUBLICATION_FIELDS}


def collect_backing_documents(store: BackedGradientStore, payloads: Sequence[Mapping[str, Any]], *,
                              require_complete: bool = True) -> list[dict]:
    """Freeze actual backing versions, including their captured opposite versions.
    冻结实际背板版本，包括采集时使用的对侧版本。

    Args:
        store: Source library.（来源材料库。）
        payloads: Measurement/fit documents with frozen identities.（带固定身份的采集或拟合文档。）
        require_complete: Reject missing source versions for new snapshots.
            （新快照是否拒绝缺失的来源版本。）
    Returns:
        Complete saved documents without regenerating version identities.
        （完整已存文档，保持原版本身份。）
    """
    from core.backed_gradient_backing_store import get_backing_material
    from core.backed_gradient_product_store import uses_reference_backings

    documents: dict[tuple[str, str], dict] = {}
    requests: list[tuple[str, str]] = []
    references = []
    for payload in payloads:
        for document in payload.get("backing_documents", []):
            key = (document["material_id"], document["version_id"])
            if key in documents and _immutable(documents[key]) != _immutable(document):
                raise BackedGradientConflictError("A backing version belongs to different saved data.")
            documents[key] = deepcopy(document)
        workflow = payload.get("capture_export", {}).get("dataset", {}).get("workflow", {})
        for source in (payload, workflow):
            identities = source.get("backing_material_ids", {})
            for field in ("capture_backing_material_versions", "backing_material_versions"):
                requests.extend((identity, source[field][role]) for role, identity in identities.items()
                                if role in source.get(field, {}))
        reference = payload.get("reference", {})
        if reference.get("source", {}).get("independent_backings") and uses_reference_backings(payload, reference):
            references.append(reference)

    def include(identity: str, version: str) -> None:
        key = (identity, version)
        if key not in documents:
            if not require_complete and not store.database.is_file():
                return
            try:
                document = get_backing_material(store, identity, version_id=version)
            except BackedGradientNotFoundError as exc:
                if require_complete:
                    raise CoreValidationError("The selected calibration is missing a matching backing model version. Re-export the material from the source computer with its backing records, then import it again.") from exc
                return
            documents[key] = document

    for identity, version in requests:
        include(identity, version)
    # Older archives may know the fitted reference but predate embedded versions.
    for reference in references:
        for identity in reference["source"].get("backing_material_ids", {}).values():
            if any(item["material_id"] == identity and item.get("reference_id") == reference["reference_id"]
                   for item in documents.values()):
                continue
            found = None
            if store.database.is_file():
                with store._connection() as connection:
                    rows = connection.execute(
                        "SELECT document FROM gradient_backing_material_versions WHERE material_id=? ORDER BY rowid DESC", (identity,))
                    found = next((item for (raw,) in rows if (item := json.loads(raw)).get("reference_id") == reference["reference_id"]), None)
            if found is not None:
                documents[(identity, found["version_id"])] = found
            elif require_complete:
                raise CoreValidationError("The selected calibration is missing its saved backing version.")
    scanned = set()
    while pending := [key for key in documents if key not in scanned]:
        for key in pending:
            scanned.add(key)
            snapshot = documents[key]["snapshot"]
            if snapshot.get("opposite_version_id"):
                include(snapshot["opposite_material_id"], snapshot["opposite_version_id"])
    return list(documents.values())


def _validate_document(document: Any) -> dict:
    from core.backed_gradient_transfer import _prepare

    try:
        if not isinstance(document, dict) or _digest(_immutable(document)) != document["version_id"]:
            raise CoreValidationError("A backing version's saved content hash does not match.")
        identity, opposite = _uuid(document["material_id"]), _uuid(document["opposite_material_id"])
        role, snapshot = document["role"], document["snapshot"]
        if (identity == opposite or role not in ("W", "K") or document["status"] not in ("ready", "measured")
                or any(snapshot.get(key) != document[key] for key in ("material_id", "role", "dataset_id", "opposite_material_id"))
                or _xyz(document["bare_xyz"]) != _xyz(snapshot["bare_xyz"])):
            raise CoreValidationError("A backing version has inconsistent captured identities.")
        dataset, rows, selection = _prepare(snapshot["capture_export"], allow_independent_backing=True)
        workflow = dataset.get("workflow", {})
        if (dataset["dataset_id"] != document["dataset_id"] or workflow.get("kind") != "backing_material"
                or workflow.get("backing_material_id") != identity or workflow.get("material_symbol") != role):
            raise CoreValidationError("A backing version belongs to another capture.")
        selected = {record["record_id"]: {**record, "selected": True} for record, _, deleted_at in rows
                    if deleted_at is None and record["record_id"] in selection.values()}
        if (set(snapshot["selected_record_ids"]) != set(selected)
                or {row["record_id"]: row for row in snapshot["samples"]} != selected
                or snapshot["dataset_revision"] != dataset["revision"]):
            raise CoreValidationError("A backing version does not match its selected original readings.")
        opposite_role = "K" if role == "W" else "W"
        if any(record["material_symbol"] != role or record["backing"] != (
                role if record["sample_role"] == "bare_backing" else opposite_role) for record, _, _ in rows):
            raise CoreValidationError("A backing capture contains another material's readings.")
        if document["status"] == "ready":
            component = BackedGradientComponent.from_dict(document["component"])
            reference = BackedGradientReference.from_dict(document["reference"])
            if component.to_dict() != document["component"] or reference.reference_id != document["reference_id"]:
                raise CoreValidationError("A backing version has inconsistent optical parameters.")
        return deepcopy(document)
    except (KeyError, TypeError, ValueError) as exc:
        raise CoreValidationError("The archive contains an invalid saved backing version.") from exc


def restore_material_captures(store: BackedGradientStore, entries: Sequence[tuple[dict, dict, list[dict]]]) -> None:
    """Restore an archive batch's captures and immutable backings atomically.
    原子恢复一批档案的采集记录与不可变背板版本。

    Args:
        store: Destination library.（目标材料库。）
        entries: Measurements, fits, and optional legacy bundle supplements.
            （采集、拟合及可选旧版导出包补充资料。）
    """
    from core.backed_gradient_product_store import _save_backing_reference, backing_group_id
    from core.backed_gradient_transfer import _import_prepared_gradient, _prepare

    documents: dict[str, dict] = {}
    captures = []
    fits = []
    preferred: dict[str, dict] = {}
    for measurements, fit, supplement in entries:
        for raw in [*measurements.get("backing_documents", []), *fit.get("backing_documents", []), *supplement]:
            document = _validate_document(raw)
            version = document["version_id"]
            if version in documents and _immutable(documents[version]) != _immutable(document):
                raise BackedGradientConflictError("An imported backing version belongs to different saved data.")
            documents[version] = document
        if isinstance(measurements.get("capture_export"), dict):
            captures.append(_prepare(measurements["capture_export"], allow_independent_backing=True))
        fits.append((fit["reference"], str(measurements.get("name") or "Imported Box backing")))
        identities = measurements.get("backing_material_ids", {})
        components = fit.get("backing_components") or measurements.get("backing_components", {})
        for role, identity in identities.items():
            matches = [item for item in documents.values() if item["material_id"] == identity
                       and item.get("reference_id") == fit["reference"]["reference_id"]
                       and item.get("component") == components.get(role)]
            if matches:
                preferred[identity] = matches[-1]
    for document in documents.values():
        captures.append(_prepare(document["snapshot"]["capture_export"], allow_independent_backing=True))
        preferred.setdefault(document["material_id"], document)

    with store._connection(write=True) as connection:
        # Imported history must not replace a calibration already chosen locally.
        prior_references = {}
        for (raw,) in connection.execute("SELECT document FROM gradient_references ORDER BY rowid DESC"):
            item = json.loads(raw)
            prior_references.setdefault(backing_group_id(item["reference"]), item["reference_id"])
        for dataset, rows, selection in captures:
            _import_prepared_gradient(connection, store, dataset, rows, selection)
        for version, document in documents.items():
            prior = connection.execute("SELECT document FROM gradient_backing_material_versions WHERE version_id=?", (version,)).fetchone()
            if prior is not None and _immutable(json.loads(prior[0])) != _immutable(document):
                raise BackedGradientConflictError("An imported backing version belongs to different saved data.")
            if document["status"] == "ready":
                _save_backing_reference(connection, document["reference"], document["name"])
            document.setdefault("updated_at", _now())
            document.setdefault("active_dataset_id", document["dataset_id"])
            if prior is None:
                connection.execute("INSERT INTO gradient_backing_material_versions VALUES (?,?,?)",
                                   (version, document["material_id"], _json(document)))
        for reference, name in fits:
            _save_backing_reference(connection, reference, name)
        for identity, document in preferred.items():
            prior = connection.execute("SELECT document FROM gradient_backing_materials WHERE material_id=?", (identity,)).fetchone()
            if prior is not None:
                if json.loads(prior[0])["role"] != document["role"]:
                    raise BackedGradientConflictError("An imported backing material has a different saved role.")
                continue
            document.setdefault("updated_at", _now())
            document.setdefault("active_dataset_id", document["dataset_id"])
            connection.execute("INSERT INTO gradient_backing_materials VALUES (?,?)", (identity, _json(document)))
        for reference_id in prior_references.values():
            connection.execute("UPDATE gradient_references SET rowid=(SELECT COALESCE(MAX(rowid),0)+1 FROM gradient_references) WHERE reference_id=?",
                               (reference_id,))
