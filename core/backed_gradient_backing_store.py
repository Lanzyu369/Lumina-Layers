"""Independent backing identities and immutable captured versions.
独立背板身份与不可变采集版本。
"""
from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
from typing import Any
from uuid import uuid4

from core.backed_gradient_material import BackedGradientComponent, BackedGradientReference
from core.backed_gradient_store import (
    BackedGradientConflictError, BackedGradientNotFoundError, BackedGradientStore,
    THICKNESSES_MM, _digest, _json, _now, _text, _uuid, _xyz,
)
from core.errors import CoreValidationError


def _opposite(role: str) -> str:
    if role not in ("W", "K"):
        raise CoreValidationError("Choose a white or black backing material.")
    return "K" if role == "W" else "W"


def create_black_white_pair(store: BackedGradientStore, payload: dict) -> dict:
    """Create two mutually linked captures in one transaction.
    在同一事务中创建互相关联的黑白耗材采集。

    Args:
        store: Capture storage.（采集存储。）
        payload: White and black material identities.（黑白耗材身份。）
    Returns:
        White capture, with its partner already registered.（已关联黑色耗材的白色采集。）
    """
    identities = {role: payload[key] for role, key in (("W", "white"), ("K", "black"))}
    if (identities["W"]["name"].strip(), identities["W"].get("brand", "").strip()) == (
            identities["K"]["name"].strip(), identities["K"].get("brand", "").strip()):
        raise CoreValidationError("Give the white and black materials distinct names.")
    ids = {role: str(uuid4()) for role in identities}
    datasets, documents = {}, {}
    for role, identity in identities.items():
        opposite = _opposite(role)
        workflow = {"kind": "backing_material", "material_symbol": role, "role": role,
                    "backing_material_id": ids[role], "opposite_material_id": ids[opposite]}
        dataset = store._new_dataset({**identity, "materials": {key: item["name"] for key, item in identities.items()}},
                                     workflow=workflow)
        datasets[role] = dataset
        documents[role] = {"material_id": ids[role], "role": role,
                           **{key: dataset[key] for key in ("name", "brand", "material_type", "dataset_id", "created_at", "updated_at")},
                           "active_dataset_id": dataset["dataset_id"], "opposite_material_id": ids[opposite], "status": "draft"}
    with store._connection(write=True) as connection:
        for role in identities:
            connection.execute("INSERT INTO gradient_datasets VALUES (?,?)", (datasets[role]["dataset_id"], _json(datasets[role])))
            connection.execute("INSERT INTO gradient_backing_materials VALUES (?,?)", (ids[role], _json(documents[role])))
        return store._read_dataset(connection, datasets["W"]["dataset_id"])


def list_backing_materials(store: BackedGradientStore) -> list[dict]:
    """List independently registered black/white materials.
    列出独立登记的黑白耗材。

    Args:
        store: Capture storage.（采集存储。）
    Returns:
        Current material entities.（当前背板实体。）
    """
    projected = {}
    with store._connection() as connection:
        for (raw,) in connection.execute("SELECT document FROM gradient_backing_materials ORDER BY rowid"):
            document = json.loads(raw)
            projected[document["material_id"]] = document
    return list(projected.values())


def get_backing_material(store: BackedGradientStore, material_id: str, *, version_id: str | None = None) -> dict:
    """Read a backing or one immutable saved version. / 读取背板或指定不可变版本。

    Args:
        store: Capture storage.（采集存储。）
        material_id: Stable backing identity.（稳定背板身份。）
        version_id: Optional frozen version.（可选固定版本。）
    Returns:
        Self-contained backing document.（自包含背板资料。）
    """
    identity = _uuid(material_id)
    with store._connection() as connection:
        if version_id:
            row = connection.execute("SELECT document FROM gradient_backing_material_versions WHERE material_id=? AND version_id=?",
                                     (identity, version_id)).fetchone()
        else:
            row = connection.execute("SELECT document FROM gradient_backing_materials WHERE material_id=?", (identity,)).fetchone()
    if row:
        return json.loads(row[0])
    raise BackedGradientNotFoundError("The backing material was not found.")


def create_backing_material_dataset(store: BackedGradientStore, payload: dict) -> dict:
    """Start a black/white material against its registered opposite material.
    基于已登记的另一侧耗材开始黑白耗材采集。

    Args:
        store: Capture storage.（采集存储。）
        payload: Own identity and selected opposite material.（自身身份及选定的另一侧耗材。）
    Returns:
        Empty independent capture dataset.（空的独立采集表。）
    """
    role = payload.get("role")
    opposite_role = _opposite(role)
    identity = {key: payload[key] for key in ("name", "brand", "material_type", "batch", "notes") if key in payload}
    identity["name"] = _text(identity.get("name"), "name", 200, required=True)
    existing = get_backing_material(store, payload["material_id"]) if payload.get("material_id") else None
    if existing and existing["role"] != role:
        raise BackedGradientConflictError("A backing material cannot change its white/black role.")
    material_id = existing["material_id"] if existing else str(uuid4())
    opposite_id = payload.get("opposite_material_id") or (existing or {}).get("opposite_material_id")
    if not opposite_id:
        raise CoreValidationError("Create the first black and white materials together.")
    opposite = get_backing_material(store, opposite_id)
    if opposite["role"] != opposite_role:
        raise CoreValidationError("Choose a backing of the opposite role.")
    if existing is None and opposite["status"] != "ready":
        raise CoreValidationError("Complete the opposite material profile before adding another material.")
    identity["materials"] = {role: identity["name"], opposite_role: opposite["name"]}
    workflow = {"kind": "backing_material", "material_symbol": role, "role": role,
                "backing_material_id": material_id, "opposite_material_id": opposite["material_id"]}
    if opposite.get("version_id") and opposite["status"] == "ready":
        workflow["opposite_version_id"] = opposite["version_id"]
    dataset = store._create(identity, workflow=workflow)
    document = deepcopy(existing) if existing else {
        "material_id": material_id, "role": role, "name": identity["name"],
        "brand": dataset["brand"], "material_type": dataset["material_type"],
        "status": "draft", "dataset_id": dataset["dataset_id"], "created_at": _now(),
    }
    document.update(active_dataset_id=dataset["dataset_id"], updated_at=_now())
    if not existing or not existing.get("version_id"):
        document.update(opposite_material_id=opposite["material_id"], name=identity["name"],
                        brand=dataset["brand"], material_type=dataset["material_type"])
    with store._connection(write=True) as connection:
        connection.execute("INSERT OR REPLACE INTO gradient_backing_materials VALUES (?,?)",
                           (document["material_id"], _json(document)))
    return dataset


def backing_material_snapshot(store: BackedGradientStore, dataset_id: str) -> dict[str, Any]:
    """Freeze seven cross-backed samples and this material's bare three-mm piece.
    冻结七张异底样片及该耗材自己的三毫米裸片。

    Args:
        store: Capture storage.（采集存储。）
        dataset_id: Independent backing capture.（独立背板采集身份。）
    Returns:
        Own measurements and the selected opposite backing.（自身读数和选定对侧背板。）
    """
    dataset = store.get(dataset_id)
    workflow = dataset.get("workflow", {})
    if workflow.get("kind") != "backing_material":
        raise CoreValidationError("Choose an independent backing capture.")
    role = workflow["material_symbol"]
    opposite_role = _opposite(role)
    selected = [row for row in dataset["captures"] if row["selected"]]
    samples = [row for row in selected if row["sample_role"] == "coated" and row["material_symbol"] == role and row["backing"] == opposite_role]
    bare = next((row for row in selected if row["sample_role"] == "bare_backing" and row["material_symbol"] == role), None)
    present = {row["overlay_mm"] for row in samples}
    missing = [f"{thickness:.2f}" for thickness in THICKNESSES_MM if thickness not in present]
    if bare is None:
        missing.append("3.00 mm bare")
    if missing:
        raise CoreValidationError("Complete the missing backing readings: " + ", ".join(missing))
    opposite = get_backing_material(store, workflow["opposite_material_id"], version_id=workflow.get("opposite_version_id"))
    snapshot = {
        "material_id": workflow["backing_material_id"], "role": role, "material_symbol": role,
        "dataset_id": dataset_id, "dataset_revision": dataset["revision"],
        **{key: dataset[key] for key in ("name", "brand", "material_type", "notes")},
        "opposite_material_id": opposite["material_id"], "opposite_version_id": opposite.get("version_id"),
        "opposite": opposite, "samples": deepcopy([*samples, bare]), "bare_xyz": deepcopy(bare["reflectance_percent_xyz"]),
        "reference_anchors": {role: deepcopy(bare["reflectance_percent_xyz"])},
        "capture_history": deepcopy(dataset["captures"]), "capture_export": store.export(dataset_id),
        "selected_record_ids": sorted(row["record_id"] for row in [*samples, bare]),
        "conditions": {"total_mm": 3., "observation_face": "bed_contact", "diffuser_removed": True},
    }
    if opposite["status"] == "ready":
        snapshot.update(reference=deepcopy(opposite["reference"]), opposite_component=deepcopy(opposite["component"]))
    snapshot["input_hash"] = _digest(snapshot)
    return snapshot


def save_backing_material_result(store: BackedGradientStore, snapshot: dict, result: dict | None) -> dict:
    """Save this material independently, preserving earlier immutable versions.
    单独保存这种背板，并保留之前的不可变版本。

    Args:
        store: Capture storage.（采集存储。）
        snapshot: Frozen own readings.（固定自身读数。）
        result: Component/reference fit, or None to save measured data.（组件与观测标定，或仅保存读数。）
    Returns:
        Saved independent backing version.（独立背板的新版本。）
    """
    return save_backing_material_results(store, [(snapshot, result)])[0]


def _prepare_backing_material_result(store: BackedGradientStore, snapshot: dict, result: dict | None) -> dict:
    material_id = _uuid(snapshot["material_id"])
    role = snapshot["role"]
    _opposite(role)
    previous = get_backing_material(store, material_id)
    if previous["role"] != role:
        raise BackedGradientConflictError("The backing capture belongs to a different material role.")
    frozen = {key: deepcopy(value) for key, value in snapshot.items() if key != "opposite"}
    document = {key: deepcopy(snapshot[key]) for key in ("material_id", "role", "name", "brand", "material_type", "dataset_id", "opposite_material_id")}
    document.update(snapshot=frozen, bare_xyz=_xyz(snapshot["bare_xyz"]),
                    status="ready" if result is not None else "measured", created_at=previous["created_at"])
    if result is not None:
        component = BackedGradientComponent.from_dict(result["component"])
        reference = BackedGradientReference.from_dict(result["reference"])
        document.update(component=component.to_dict(), reference=reference.to_dict(),
                        reference_id=reference.reference_id, fit=deepcopy(result))
    document["version_id"] = _digest(document)
    return document


def save_backing_material_results(store: BackedGradientStore, entries: list[tuple[dict, dict | None]]) -> list[dict]:
    """Publish independent results together in one transaction.
    在同一个事务中发布多份独立背板结果。

    Args:
        store: Capture storage.（采集存储。）
        entries: Frozen measurements and optional fitted results.（固定读数及可选拟合结果。）
    Returns:
        Saved versions in input order.（按输入顺序返回的已保存版本。）
    """
    documents = [_prepare_backing_material_result(store, snapshot, result) for snapshot, result in entries]
    if len({document["material_id"] for document in documents}) != len(documents):
        raise CoreValidationError("Publish only one result per backing material in a transaction.")
    with store._connection(write=True) as connection:
        return _write_backing_material_results(connection, documents)


def _write_backing_material_results(connection: sqlite3.Connection, documents: list[dict], *,
                                    expected_current_versions: dict[str, str] | None = None) -> list[dict]:
    from core.backed_gradient_product_store import _save_backing_reference

    saved = []
    for document in documents:
        old = connection.execute("SELECT document FROM gradient_backing_material_versions WHERE version_id=?",
                                 (document["version_id"],)).fetchone()
        if old:
            saved.append(json.loads(old[0]))
            continue
        if document["status"] == "ready":
            _save_backing_reference(connection, document["reference"], document["name"])
        document.update(updated_at=_now(), active_dataset_id=document["dataset_id"])
        connection.execute("INSERT INTO gradient_backing_material_versions VALUES (?,?,?)",
                           (document["version_id"], document["material_id"], _json(document)))
        current = connection.execute("SELECT document FROM gradient_backing_materials WHERE material_id=?",
                                     (document["material_id"],)).fetchone()
        previous = json.loads(current[0]) if current else {}
        if (expected_current_versions is None
                or previous.get("version_id") == expected_current_versions.get(document["material_id"])):
            current_document = deepcopy(document)
            if expected_current_versions is not None and current:
                current_document["active_dataset_id"] = previous.get("active_dataset_id", document["dataset_id"])
            connection.execute("INSERT OR REPLACE INTO gradient_backing_materials VALUES (?,?)",
                               (document["material_id"], _json(current_document)))
        saved.append(document)
    return saved


def backing_versions_for_reference(store: BackedGradientStore, reference: dict) -> dict[str, dict]:
    """Resolve the initial backing identities to models at one observation version.
    将首建背板身份解析到指定观测版本下的模型。

    Args:
        store: Capture storage.（采集存储。）
        reference: Initial calibration or its joint refinement.（初建标定或其联合完善版本。）
    Returns:
        Immutable W/K backing documents.（不可变黑白背板版本。）
    """
    identities = reference.get("source", {}).get("backing_material_ids", {})
    if set(identities) != {"W", "K"}:
        raise CoreValidationError("The observation reference is missing its original backing identities.")
    found = {}
    with store._connection() as connection:
        for role, identity in identities.items():
            rows = connection.execute(
                "SELECT document FROM gradient_backing_material_versions WHERE material_id=? ORDER BY rowid DESC",
                (identity,),
            )
            found[role] = None
            for (raw,) in rows:
                item = json.loads(raw)
                if item.get("reference_id") == reference["reference_id"]:
                    found[role] = item
                    break
    if any(item is None for item in found.values()):
        raise CoreValidationError("The selected calibration is missing a matching backing model version. Re-export the material from the source computer with its backing records, then import it again.")
    return found


def backing_selection(store: BackedGradientStore, white_id: str, black_id: str) -> dict:
    """Freeze independent actual backings using their common observation scale.
    使用共同观测尺度冻结独立选择的实际黑白背板。

    Args:
        store: Capture storage.（采集存储。）
        white_id: White material identity.（白背板身份。）
        black_id: Black material identity.（黑背板身份。）
    Returns:
        Capture workflow fields.（采集流程字段。）
    """
    pair = {"W": get_backing_material(store, white_id), "K": get_backing_material(store, black_id)}
    if any(item["role"] != role or item["status"] != "ready" for role, item in pair.items()):
        raise CoreValidationError("Select a completed white backing and a completed black backing.")
    if pair["W"]["reference_id"] != pair["K"]["reference_id"]:
        raise CoreValidationError("The selected backings use different measurement calibrations. Recollect one against the other backing.")
    return {"reference_id": pair["W"]["reference_id"],
            "backing_material_ids": {role: item["material_id"] for role, item in pair.items()},
            "backing_material_versions": {role: item["version_id"] for role, item in pair.items()},
            "backing_components": {role: deepcopy(item["component"]) for role, item in pair.items()},
            "backing_materials": {role: {key: deepcopy(item[key]) for key in ("material_id", "version_id", "name", "brand", "material_type", "role")} for role, item in pair.items()}}
