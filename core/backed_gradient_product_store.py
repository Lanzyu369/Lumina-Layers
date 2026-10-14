"""Single-material capture identities and reusable backing references.
单耗材采集身份及可复用黑白背板标定。
"""

from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
from typing import Any

from core.backed_gradient_store import (
    CAPTURE_MATERIAL_SYMBOLS, SINGLE_MATERIAL_SYMBOL, THICKNESSES_MM, BackedGradientConflictError,
    BackedGradientNotFoundError, BackedGradientStore, _digest, _json, _now, _text,
)
from core.errors import CoreValidationError


def backing_group_id(reference: dict) -> str:
    """Return the stable physical backing group. / 返回稳定的实体背板组身份。

    Args:
        reference: Versioned optical reference.（带版本的光学参考。）
    Returns:
        Group identity shared by successive fits.（多次拟合共享的组身份。）
    """
    source = reference.get("source", {})
    return str(source.get("backing_id") or source.get("dataset_id") or reference["reference_id"])


def _reference_document(document: dict) -> dict:
    source = document["reference"].get("source", {})
    history = source.get("capture_history", [])
    conditions = history[0].get("capture_context", {}) if history else {}
    materials = source.get("materials", {})
    if not materials:
        materials = conditions.get("materials", {})
    return {**document, "backing_id": backing_group_id(document["reference"]),
            "version": int(document.get("version", 1)),
            "source_dataset_id": source.get("dataset_id"),
            "brand": source.get("brand") or conditions.get("brand", ""),
            "material_type": source.get("material_type") or conditions.get("material_type", ""),
            "white_name": materials.get("W", ""), "black_name": materials.get("K", "")}


def save_backing_reference(store: BackedGradientStore, reference: dict, name: str) -> dict:
    """Persist a complete immutable backing reference. / 保存完整不可变背板标定。

    Args:
        store: Capture storage.（采集存储。）
        reference: Self-contained physical reference.（自包含光学标定。）
        name: User-facing reference name.（标定显示名称。）

    Returns:
        Saved reference and display metadata.（标定及显示信息。）
    """
    with store._connection(write=True) as connection:
        return _save_backing_reference(connection, reference, name)


def _save_backing_reference(connection: sqlite3.Connection, reference: dict, name: str) -> dict:
    from core.backed_gradient_material import BackedGradientReference

    parsed = BackedGradientReference.from_dict(reference)
    group_id = backing_group_id(parsed.to_dict())
    document = {"reference_id": parsed.reference_id, "name": _text(name, "name", 200, required=True),
                "reference": parsed.to_dict(), "created_at": _now(), "backing_id": group_id}
    prior = connection.execute("SELECT document FROM gradient_references WHERE reference_id=?",
                               (parsed.reference_id,)).fetchone()
    if prior:
        previous = _reference_document(json.loads(prior[0]))
        if previous["reference"] != document["reference"]:
            raise BackedGradientConflictError("This backing reference ID already belongs to a different saved version.")
        return previous
    versions = [_reference_document(json.loads(row[0])) for row in connection.execute("SELECT document FROM gradient_references")]
    document["version"] = 1 + max((item["version"] for item in versions if item["backing_id"] == group_id), default=0)
    connection.execute("INSERT INTO gradient_references VALUES (?,?)",
                       (parsed.reference_id, _json(document)))
    return _reference_document(document)


def list_backing_references(store: BackedGradientStore) -> list[dict]:
    """List reusable references, newest first. / 按新到旧列出可复用标定。

    Args:
        store: Capture storage.（采集存储。）

    Returns:
        Complete saved references.（已保存完整标定。）
    """
    with store._connection() as connection:
        documents = [_reference_document(json.loads(row[0])) for row in connection.execute(
            "SELECT document FROM gradient_references ORDER BY rowid DESC")]
    groups: dict[str, dict] = {}
    for document in documents:
        groups.setdefault(document["backing_id"], document)
    return list(groups.values())


def get_backing_reference(store: BackedGradientStore, reference_id: str) -> dict:
    """Read one saved reference. / 读取一个已存标定。

    Args:
        store: Capture storage.（采集存储。）
        reference_id: Reference content identity.（标定内容身份。）

    Returns:
        Saved reference document.（标定文档。）
    """
    with store._connection() as connection:
        row = connection.execute("SELECT document FROM gradient_references WHERE reference_id=?",
                                 (reference_id,)).fetchone()
    if row is None:
        raise BackedGradientNotFoundError("The saved backing reference was not found.")
    return _reference_document(json.loads(row[0]))


def latest_backing_reference(store: BackedGradientStore, reference_id: str) -> dict:
    """Resolve an original capture reference to its current group version.
    将采集时的参考解析为同背板组的当前版本。

    Args:
        store: Capture storage.（采集存储。）
        reference_id: Immutable original reference.（不可变原始参考。）
    Returns:
        Newest reference in the same backing group.（同背板组最新参考。）
    """
    original = get_backing_reference(store, reference_id)
    return next((item for item in list_backing_references(store) if item["backing_id"] == original["backing_id"]), original)


def uses_reference_backings(snapshot: dict, reference: dict | None = None) -> bool:
    """Identify captures printed with the reference's actual initial materials.
    识别实际使用该观测参考初始底材打印的采集。

    Args:
        snapshot: Capture workflow or material snapshot.（采集流程或耗材快照。）
        reference: Observation calibration when absent from the snapshot.（快照未含参考时显式提供观测标定。）
    Returns:
        Whether shared refinement can use the same two physical materials.
        （联合完善是否对应同两种实际底材。）
    """
    if not snapshot.get("backing_components"):
        return True
    observation = reference or snapshot.get("reference", {})
    initial = observation.get("source", {}).get("backing_material_ids", {})
    return (set(initial) == {"W", "K"} and snapshot.get("backing_material_ids") == initial
            and snapshot["backing_components"] == {"W": observation.get("white"), "K": observation.get("black")})


def _refresh_backing_models(store: BackedGradientStore, snapshot: dict, reference: dict,
                            captured_reference: dict) -> None:
    if not snapshot.get("backing_components") or not uses_reference_backings(snapshot, captured_reference):
        return
    from core.backed_gradient_backing_store import backing_versions_for_reference

    versions = backing_versions_for_reference(store, reference)
    snapshot.setdefault("capture_backing_material_versions", deepcopy(snapshot["backing_material_versions"]))
    snapshot["backing_material_versions"] = {role: item["version_id"] for role, item in versions.items()}
    snapshot["backing_components"] = {role: deepcopy(item["component"]) for role, item in versions.items()}
    snapshot["backing_materials"] = {
        role: {key: deepcopy(item[key]) for key in ("material_id", "version_id", "name", "brand", "material_type", "role")}
        for role, item in versions.items()
    }


def create_material_dataset(store: BackedGradientStore, payload: dict) -> dict:
    """Create an independent material capture against a saved backing reference.
    基于已存背板标定创建独立耗材采集。

    Args:
        store: Capture storage.（采集存储。）
        payload: Material identity and explicitly chosen backing reference.（耗材身份及明确选用的背板标定。）

    Returns:
        Empty durable material capture.（空的持久耗材采集。）
    """
    symbol = payload.get("material_symbol", SINGLE_MATERIAL_SYMBOL)
    if symbol in ("W", "K"):
        raise CoreValidationError("Create black and white materials through the black/white profile workflow.")
    if symbol not in CAPTURE_MATERIAL_SYMBOLS:
        raise CoreValidationError("Invalid material capture identity.")
    selected_backings = {}
    if payload.get("white_backing_id") or payload.get("black_backing_id"):
        from core.backed_gradient_backing_store import backing_selection

        selected_backings = backing_selection(store, payload.get("white_backing_id", ""), payload.get("black_backing_id", ""))
    reference = get_backing_reference(store, selected_backings.get("reference_id") or payload.get("reference_id", ""))
    identity = {key: payload[key] for key in ("name", "brand", "material_type", "batch", "notes") if key in payload}
    identity["materials"] = {symbol: payload["name"]}
    return store._create(identity, workflow={"kind": "material", "material_symbol": symbol,
                                            "reference_id": reference["reference_id"],
                                            "backing_id": reference["backing_id"],
                                            "backing_reference": reference, **selected_backings})


def create_backing_dataset(store: BackedGradientStore, payload: dict) -> dict:
    """Create the one-time black/white backing setup. / 创建一次性黑白背板设置。

    Args:
        store: Capture storage.（采集存储。）
        payload: Reference and backing material names.（标定及背板材料名称。）

    Returns:
        Durable backing capture.（持久背板采集。）
    """
    identity = {key: payload[key] for key in ("name", "brand", "material_type", "batch", "notes") if key in payload}
    identity["materials"] = {"W": payload["white_name"], "K": payload["black_name"]}
    return store._create(identity, workflow={"kind": "backing_reference"})


def material_snapshot(store: BackedGradientStore, dataset_id: str, *, material_symbol: str | None = None,
                      reference_id: str | None = None) -> dict[str, Any]:
    """Freeze only one material's paired readings and selected reference.
    仅冻结一种材料的黑白底读数及选用标定。

    Args:
        store: Capture storage.（采集存储。）
        dataset_id: Current or historical capture ID.（当前或历史采集身份。）
        material_symbol: Optional selection from a historical multi-material capture.
            （从历史多材料记录选定的颜色。）
        reference_id: Saved reference for the historical capture.（历史采集使用的标定。）

    Returns:
        Complete frozen fitter input with raw history.（包含原始历史的完整拟合输入。）
    """
    dataset = store.get(dataset_id)
    workflow = dataset.get("workflow", {})
    symbol = material_symbol or workflow.get("material_symbol")
    reference_key = reference_id or workflow.get("reference_id")
    if symbol not in CAPTURE_MATERIAL_SYMBOLS or not reference_key:
        raise CoreValidationError("Select a material and a saved backing reference.")
    if workflow.get("kind") == "material":
        original = get_backing_reference(store, workflow["reference_id"])
        selected_reference = get_backing_reference(store, reference_key)
        if symbol != workflow["material_symbol"] or selected_reference["backing_id"] != original["backing_id"]:
            raise BackedGradientConflictError("This capture belongs to another material or backing reference.")
        reference_key = workflow["reference_id"]
    elif get_backing_reference(store, reference_key)["reference"].get("source", {}).get("dataset_id") != dataset_id:
        raise BackedGradientConflictError("Use the backing reference measured with this historical capture.")
    original_reference = get_backing_reference(store, reference_key)
    reference = (latest_backing_reference(store, reference_key)
                 if uses_reference_backings(workflow, original_reference["reference"]) else original_reference)
    records = [row for row in dataset["captures"] if row["material_symbol"] == symbol and row["sample_role"] == "coated"]
    selected = [row for row in records if row["selected"]]
    _require_pairs(selected, (symbol,), controls=True)
    capture_export = store.export(dataset_id)
    bare_records = [row for row in dataset["captures"] if row["sample_role"] == "bare_backing"]
    capture_export["dataset"]["captures"] = deepcopy(records + bare_records)
    capture_export["dataset"]["selected_capture_ids"] = {
        slot: identity for slot, identity in dataset["selected_capture_ids"].items()
        if slot.startswith(symbol + ":") or slot.startswith("bare:")
    }
    capture_export["deleted_receipts"] = [item for item in capture_export["deleted_receipts"]
                                           if item["record"]["material_symbol"] == symbol
                                           or item["record"]["sample_role"] == "bare_backing"]
    snapshot = {"dataset_id": dataset_id, "dataset_revision": dataset["revision"],
                "name": dataset["materials"][symbol], "brand": dataset["brand"],
                "material_type": dataset["material_type"], "notes": dataset["notes"],
                "material_symbol": symbol, "material_kind": {"W": "white", "K": "black"}.get(symbol, "color"),
                "reference": reference["reference"], "reference_id": reference["reference_id"],
                "capture_reference_id": reference_key, "backing_id": reference["backing_id"],
                "conditions": {"total_mm": 3., "observation_face": "bed_contact", "diffuser_removed": True},
                "samples": deepcopy(selected), "capture_history": deepcopy(records), "capture_export": capture_export,
                "selected_record_ids": sorted(row["record_id"] for row in selected)}
    for key in ("backing_components", "backing_material_ids", "backing_material_versions", "backing_materials"):
        if key in workflow:
            snapshot[key] = deepcopy(workflow[key])
    if reference["reference_id"] != reference_key:
        _refresh_backing_models(store, snapshot, reference["reference"], original_reference["reference"])
    if snapshot.get("backing_material_ids"):
        from core.backed_gradient_backing_transfer import collect_backing_documents

        snapshot["backing_documents"] = collect_backing_documents(store, [snapshot])
    snapshot["input_hash"] = _digest(snapshot)
    if dataset_id == reference["reference"].get("source", {}).get("dataset_id") and symbol in ("W", "K"):
        snapshot["backing_role"] = symbol
        snapshot["input_hash"] = _digest({key: value for key, value in snapshot.items() if key != "input_hash"})
    return snapshot


def material_group_snapshot(store: BackedGradientStore, selected: dict) -> tuple[dict | None, list[dict]]:
    """Gather complete independently captured materials sharing one physical backing.
    汇集同一实体背板下已采集完整的独立耗材。

    Args:
        store: Capture storage.（采集存储。）
        selected: Requested material's frozen snapshot.（当前材料的冻结快照。）
    Returns:
        Compact group fitter input and full per-material inputs.（精简组拟合输入及完整单材输入。）
    """
    reference = selected["reference"]
    if not uses_reference_backings(selected, reference):
        return None, []
    source = reference.get("source", {})
    backing_samples = source.get("backing_samples") or [
        row for row in source.get("capture_history", [])
        if row.get("sample_role") == "coated" and row.get("material_symbol") in ("W", "K")
        and row.get("selected", True)
    ]
    try:
        _require_pairs(backing_samples, ("W", "K"), controls=False)
    except CoreValidationError:
        return None, []
    if selected.get("backing_role"):
        selected_rows = {(row["material_symbol"], row["backing"], row["overlay_mm"]): row for row in selected["samples"]}
        backing_samples = [selected_rows.get((row["material_symbol"], row["backing"], row["overlay_mm"]), row)
                           for row in backing_samples]
    group_id = selected["backing_id"]
    requests = {(selected["dataset_id"], selected["material_symbol"]): selected["capture_reference_id"]}
    for entry in source.get("material_inputs", []):
        requests.setdefault((entry["dataset_id"], entry["material_symbol"]), entry.get("capture_reference_id") or selected["capture_reference_id"])
    for dataset in store.list():
        workflow = dataset.get("workflow", {})
        if workflow.get("kind") == "material":
            group = workflow.get("backing_id") or backing_group_id(workflow["backing_reference"]["reference"])
            captured_reference = workflow.get("backing_reference", {}).get("reference", reference)
            if group == group_id and uses_reference_backings(workflow, captured_reference):
                requests.setdefault((dataset["dataset_id"], workflow["material_symbol"]), workflow["reference_id"])
        elif dataset["dataset_id"] == source.get("dataset_id"):
            for symbol in dataset["materials"]:
                if source.get("independent_backings") and symbol in ("W", "K"):
                    continue
                requests.setdefault((dataset["dataset_id"], symbol), selected["capture_reference_id"])
    snapshots_by_key = {}
    from core.backed_gradient_archive import load_backed_gradient_archive
    from core.backed_gradient_smooth import SPECTRAL_SMOOTH_MODEL_ID

    for path in store.root.rglob("material.json"):
        if any(part.startswith(".") for part in path.relative_to(store.root).parts):
            continue
        main = json.loads(path.read_text(encoding="utf-8"))
        if main.get("optical_model") != SPECTRAL_SMOOTH_MODEL_ID or main.get("backing_material_id"):
            continue
        _, measurements, fit = load_backed_gradient_archive(path.parent, main)
        if backing_group_id(fit["reference"]) != group_id or not uses_reference_backings(measurements):
            continue
        key = (fit["dataset_id"], fit["material_symbol"])
        snapshots_by_key[key] = {**deepcopy(measurements), "reference": deepcopy(reference),
                                 "reference_id": reference["reference_id"], "backing_id": group_id,
                                 "capture_reference_id": measurements.get("capture_reference_id")
                                 or measurements.get("reference_id") or fit["reference"]["reference_id"]}
        restored = snapshots_by_key[key]
        if measurements.get("reference_id") != reference["reference_id"]:
            _refresh_backing_models(store, restored, reference, measurements["reference"])
        if restored.get("backing_material_ids"):
            from core.backed_gradient_backing_transfer import collect_backing_documents

            restored["backing_documents"] = collect_backing_documents(store, [restored])
        restored["input_hash"] = _digest({name: value for name, value in restored.items() if name != "input_hash"})
    for (dataset_id, symbol), capture_reference_id in requests.items():
        if (dataset_id, symbol) == (selected["dataset_id"], selected["material_symbol"]):
            snapshot = selected
        else:
            try:
                snapshot = material_snapshot(store, dataset_id, material_symbol=symbol, reference_id=capture_reference_id)
            except (BackedGradientNotFoundError, CoreValidationError):
                continue
        if snapshot["backing_id"] == group_id and uses_reference_backings(snapshot, reference):
            snapshots_by_key[(dataset_id, symbol)] = snapshot
    snapshots = list(snapshots_by_key.values())
    entries = []
    fields = ("dataset_id", "dataset_revision", "input_hash", "name", "brand", "material_type", "notes",
              "material_symbol", "material_kind", "samples", "selected_record_ids", "capture_reference_id", "backing_id",
              "backing_material_ids", "backing_material_versions", "capture_backing_material_versions", "backing_components")
    for snapshot in snapshots:
        entry = {key: deepcopy(snapshot[key]) for key in fields if key in snapshot}
        if snapshot["dataset_id"] == source.get("dataset_id") and snapshot["material_symbol"] in ("W", "K"):
            entry["backing_role"] = snapshot["material_symbol"]
        entries.append(entry)
    group = {"reference": deepcopy(reference), "backing_samples": deepcopy(backing_samples), "materials": entries}
    group["input_hash"] = _digest(group)
    return group, snapshots


def backing_snapshot(store: BackedGradientStore, dataset_id: str) -> dict:
    """Freeze cross-backed W/K readings with the two bare anchors.
    冻结黑白材料互叠读数及两个裸底锚点。

    Args:
        store: Capture storage.（采集存储。）
        dataset_id: Backing setup identity.（背板设置身份。）

    Returns:
        Complete backing fitter input.（完整背板拟合输入。）
    """
    snapshot = store.snapshot(dataset_id)
    snapshot["samples"] = [row for row in snapshot["samples"] if row["material_symbol"] in ("W", "K")]
    _require_pairs(snapshot["samples"], ("W", "K"), controls=False)
    dataset = store.get(dataset_id)
    snapshot.update(name=dataset["name"], brand=dataset["brand"], material_type=dataset["material_type"],
                    capture_history=deepcopy(dataset["captures"]))
    snapshot.pop("input_hash", None)
    snapshot["input_hash"] = _digest(snapshot)
    return snapshot


def _require_pairs(samples: list[dict], symbols: tuple[str, ...], *, controls: bool) -> None:
    present = {(row["material_symbol"], row["backing"], row["overlay_mm"]) for row in samples}
    missing = [f"{symbol}:{backing}:{thickness:.2f}" for symbol in symbols for backing in ("W", "K")
               for thickness in THICKNESSES_MM if (controls or symbol != backing)
               and (symbol, backing, thickness) not in present]
    if missing:
        raise CoreValidationError("Complete the missing readings: " + ", ".join(missing))
