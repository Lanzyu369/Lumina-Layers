"""Validated, transactional experiment transfer. / 已校验的事务式实验传输。"""

from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
from typing import Any, TYPE_CHECKING

from core.backed_gradient_store import (
    DATASET_KIND, THICKNESSES_MM, BackedGradientConflictError,
    _dataset_payload, _digest, _json, _received_at, _uuid, capture_slot,
    normalize_gradient_capture,
)
from core.errors import CoreValidationError

if TYPE_CHECKING:
    from core.backed_gradient_store import BackedGradientStore


def _canonical_identity(value: object) -> str:
    identity = _uuid(value)
    if identity != value:
        raise CoreValidationError("Imported UUIDs must use canonical lowercase spelling.")
    return identity


def _capture(record: object, dataset: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(record, dict):
        raise CoreValidationError("The import contains an invalid capture.")
    copy = deepcopy(record)
    copy.pop("selected", None)
    _canonical_identity(copy.get("record_id"))
    if copy.get("dataset_id") != dataset["dataset_id"]:
        raise CoreValidationError("An imported capture belongs to a different experiment.")
    context = copy.get("capture_context")
    if not isinstance(context, dict) or any(context.get(key) != dataset[key] for key in
                                           ("brand", "material_type", "batch", "materials", "calibration_context", "observation_face")):
        raise CoreValidationError("Capture material or measurement conditions differ from the experiment.")
    source = copy.get("source")
    body = {key: copy.get(key) for key in ("capture_id", "material_symbol", "backing", "sample_role", "overlay_mm", "sample_name", "notes")}
    body["received_at"] = context.get("original_received_at", copy.get("received_at"))
    if source == "device":
        body["measurement"] = copy.get("device_measurement")
    elif source == "manual":
        body.update(reflectance_percent_xyz=copy.get("reflectance_percent_xyz"), measurement_id=copy.get("measurement_id"))
    else:
        raise CoreValidationError("An imported capture must retain its original device/manual source.")
    normalized = normalize_gradient_capture(body)
    for key, value in normalized.items():
        if key != "received_at" and copy.get(key) != value:
            raise CoreValidationError("An imported capture's original values or geometry were modified.")
    if any(_received_at(copy.get(key)) is None for key in ("created_at", "received_at")):
        raise CoreValidationError("Imported captures require creation and reception timestamps.")
    return copy, _digest({"dataset_id": dataset["dataset_id"], **normalized})


def _prepare(payload: object, *, allow_independent_backing: bool = False
             ) -> tuple[dict[str, Any], list[tuple[dict[str, Any], str, str | None]], dict[str, str]]:
    if not isinstance(payload, dict) or payload.get("kind") != "lumina_box_backed_gradient_export" or payload.get("schema_version") != "1.0":
        raise CoreValidationError("Select a backed-gradient version 1 export.")
    if len(_json(payload).encode("utf-8")) > 10 * 1024 * 1024:
        raise CoreValidationError("The experiment import must not exceed 10 MiB.")
    source = payload.get("dataset")
    if not isinstance(source, dict) or source.get("kind") != DATASET_KIND or source.get("schema_version") != "1.0":
        raise CoreValidationError("The export is missing its backed-gradient experiment.")
    _canonical_identity(source.get("dataset_id"))
    normalized = _dataset_payload({key: source.get(key) for key in ("name", "brand", "material_type", "batch", "notes", "materials")})
    if (any(source.get(key) != value for key, value in normalized.items())
            or source.get("total_mm") != 3.0 or source.get("observation_face") != "bed_contact"
            or source.get("thicknesses_mm") != list(THICKNESSES_MM)
            or type(source.get("revision")) is not int or source["revision"] < 0
            or source.get("calibration_context") != {"white_reference_mm": 3.0, "black_reference_mm": 3.0,
                                                     "diffuser_removed": True, "black_reference_material": "K"}):
        raise CoreValidationError("Imported geometry, identity or calibration conditions are unsupported.")
    if any(_received_at(source.get(key)) is None for key in ("created_at", "updated_at")):
        raise CoreValidationError("Imported experiments require creation and update timestamps.")
    captures, deleted = source.get("captures"), payload.get("deleted_receipts", [])
    selection = source.get("selected_capture_ids")
    if not isinstance(captures, list) or not isinstance(deleted, list) or len(captures) + len(deleted) > 5000 or not isinstance(selection, dict):
        raise CoreValidationError("The import requires valid capture history and selection.")
    dataset = {key: deepcopy(value) for key, value in source.items() if key not in ("captures", "selected_capture_ids")}
    workflow = dataset.get("workflow")
    if workflow is not None:
        from core.backed_gradient_material import BackedGradientReference

        allowed = ("material", "backing_reference", "backing_material") if allow_independent_backing else ("material", "backing_reference")
        if not isinstance(workflow, dict) or workflow.get("kind") not in allowed:
            raise CoreValidationError("Unsupported capture workflow.")
        if workflow["kind"] == "material":
            reference = workflow.get("backing_reference", {})
            parsed = BackedGradientReference.from_dict(reference.get("reference", {}))
            if (workflow.get("reference_id") != parsed.reference_id
                    or reference.get("reference_id") != parsed.reference_id
                    or workflow.get("material_symbol") not in dataset["materials"]):
                raise CoreValidationError("The material capture has an invalid backing reference.")
            if ("version" in reference and (type(reference["version"]) is not int or reference["version"] < 1)
                    or "created_at" in reference and _received_at(reference["created_at"]) is None):
                raise CoreValidationError("The backing reference has invalid saved version metadata.")
        elif workflow["kind"] == "backing_material":
            role = workflow.get("material_symbol")
            if (role not in ("W", "K") or workflow.get("role") != role or role not in dataset["materials"]
                    or _canonical_identity(workflow.get("backing_material_id")) == _canonical_identity(workflow.get("opposite_material_id"))):
                raise CoreValidationError("The independent backing capture has an invalid material identity.")
    rows = [(*_capture(record, dataset), None) for record in captures]
    for receipt in deleted:
        if not isinstance(receipt, dict):
            raise CoreValidationError("Invalid deleted receipt.")
        record, digest = _capture(receipt.get("record"), dataset)
        if digest != receipt.get("digest"):
            raise CoreValidationError("A deleted receipt's content hash does not match.")
        timestamp = _received_at(receipt.get("deleted_at"))
        if timestamp is None:
            raise CoreValidationError("A deleted receipt requires its deletion time.")
        rows.append((record, digest, timestamp))
    ids = [record["record_id"] for record, _, _ in rows]
    replay_ids = [(record["capture_id"], record["measurement_id"]) for record, _, _ in rows]
    if len(set(ids)) != len(ids) or len(set(replay_ids)) != len(replay_ids):
        raise CoreValidationError("The import contains duplicate capture identities.")
    available = {record["record_id"]: record for record, _, timestamp in rows if timestamp is None}
    for slot, identity in selection.items():
        if not isinstance(identity, str) or identity not in available or capture_slot(available[identity]) != slot:
            raise CoreValidationError("The imported selection does not match its captures.")
    return dataset, rows, deepcopy(selection)


def import_gradient_document(store: BackedGradientStore, payload: dict[str, Any]) -> dict[str, Any]:
    """Merge validated identities and preserve deletion receipts atomically.
    原子合并已校验身份，并保留删除回执。

    Args:
        store: Independent backed-gradient store.（独立黑白底梯度库。）
        payload: Portable experiment document.（可携实验文档。）

    Returns:
        The restored or merged experiment.（已恢复或合并实验。）
    """
    dataset, rows, selection = _prepare(payload)
    with store._connection(write=True) as connection:
        return _import_prepared_gradient(connection, store, dataset, rows, selection)


def _import_prepared_gradient(connection: sqlite3.Connection, store: BackedGradientStore,
                              dataset: dict, rows: list[tuple[dict, str, str | None]], selection: dict[str, str]) -> dict:
    from core.backed_gradient_product_store import _save_backing_reference

    identity = dataset["dataset_id"]
    existing = connection.execute("SELECT document FROM gradient_datasets WHERE dataset_id=?", (identity,)).fetchone()
    if existing:
        prior_dataset = json.loads(existing[0])
        if any(prior_dataset[key] != dataset[key] for key in ("name", "brand", "material_type", "batch", "materials", "calibration_context", "observation_face", "total_mm")):
            raise BackedGradientConflictError("The experiment ID belongs to different material or measurement conditions.")
        if prior_dataset.get("workflow") != dataset.get("workflow"):
            raise BackedGradientConflictError("The capture belongs to another material or backing reference.")
    else:
        connection.execute("INSERT INTO gradient_datasets VALUES (?,?)", (identity, _json(dataset)))
    if dataset.get("workflow", {}).get("kind") == "material":
        reference = dataset["workflow"]["backing_reference"]
        prior_reference = connection.execute("SELECT 1 FROM gradient_references WHERE reference_id=?",
                                             (reference["reference_id"],)).fetchone()
        _save_backing_reference(connection, reference["reference"], reference["name"])
        if prior_reference is None:
            # The shared saver validates optical identity; transfer retains the
            # original version metadata instead of treating import as a new fit.
            connection.execute("UPDATE gradient_references SET document=? WHERE reference_id=?",
                               (_json(reference), reference["reference_id"]))
    changed = False
    for record, digest, deleted_at in rows:
        prior = connection.execute("SELECT record_id, document, digest, deleted_at FROM gradient_captures WHERE record_id=? OR (capture_id=? AND measurement_id=?)",
                                   (record["record_id"], record["capture_id"], record["measurement_id"])).fetchone()
        if prior:
            if prior[0] != record["record_id"] or prior[2] != digest or json.loads(prior[1]) != record:
                raise BackedGradientConflictError("An imported capture identity belongs to different data.")
            if deleted_at and not prior[3]:
                connection.execute("UPDATE gradient_captures SET deleted_at=? WHERE record_id=?", (deleted_at, record["record_id"]))
                connection.execute("DELETE FROM gradient_selections WHERE dataset_id=? AND record_id=?", (identity, record["record_id"]))
                changed = True
            continue
        connection.execute("INSERT INTO gradient_captures VALUES (?,?,?,?,?,?,?)",
                           (record["record_id"], identity, record["capture_id"], record["measurement_id"], digest, _json(record), deleted_at))
        changed = True
    for slot, record_id in selection.items():
        active = connection.execute("SELECT deleted_at FROM gradient_captures WHERE record_id=?", (record_id,)).fetchone()
        current = connection.execute("SELECT record_id FROM gradient_selections WHERE dataset_id=? AND slot=?", (identity, slot)).fetchone()
        if active and active[0] is None and (not current or current[0] != record_id):
            # Existing local selection wins; merging an old export must not undo a newer choice.
            if existing and current:
                continue
            connection.execute("INSERT OR REPLACE INTO gradient_selections VALUES (?,?,?)", (identity, slot, record_id))
            changed = True
    if existing and changed:
        store._bump(connection, identity)
    return store._read_dataset(connection, identity)
