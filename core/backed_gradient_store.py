"""Independent, durable backed-gradient experiments. / 独立持久化黑白底梯度实验。"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import UUID, uuid4

from core.errors import CoreError, CoreProcessingError, CoreValidationError


THICKNESSES_MM = (0.08, 0.16, 0.24, 0.32, 0.64, 1.28, 2.00)
MATERIAL_SYMBOLS = tuple("RYBWKCMG")
SINGLE_MATERIAL_SYMBOL = "material"
CAPTURE_MATERIAL_SYMBOLS = (*MATERIAL_SYMBOLS, SINGLE_MATERIAL_SYMBOL)
DATABASE_NAME = ".lumina-box-backed-gradient.sqlite3"
DATASET_KIND = "lumina_box_backed_gradient"


class BackedGradientNotFoundError(CoreError):
    """Report an absent experiment or record. / 表示实验或记录不存在。"""

    def __init__(self, detail: str = "The backed-gradient record was not found.") -> None:
        super().__init__(detail, "backed_gradient_not_found")


class BackedGradientConflictError(CoreError):
    """Prevent identity reuse and deleted replay. / 阻止标识复用及删除后重放。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, "backed_gradient_conflict")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    try:
        document = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        document.encode("utf-8")
        return document
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise CoreValidationError("Data must contain finite UTF-8 JSON values.") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _uuid(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CoreValidationError("A valid record UUID is required.") from exc


def _text(value: object, name: str, maximum: int = 500, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise CoreValidationError(f"{name} must be {'nonempty ' if required else ''}text of at most {maximum} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise CoreValidationError(f"{name} must contain valid UTF-8 text.") from exc
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreValidationError(f"{name} must be a finite nonnegative number.")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise CoreValidationError(f"{name} must be a finite nonnegative number.") from exc
    if not math.isfinite(result) or result < 0:
        raise CoreValidationError(f"{name} must be a finite nonnegative number.")
    return result


def _xyz(value: object) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CoreValidationError("Reflection requires three finite nonnegative XYZ percentages.")
    return [_number(component, "reflectance_percent_xyz") for component in value]


def _received_at(value: object) -> str | None:
    if value is None:
        return None
    text = _text(value, "received_at", 128, required=True)
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CoreValidationError("received_at must be a timezone-aware ISO timestamp.") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise CoreValidationError("received_at must be a timezone-aware ISO timestamp.")
    return text


def capture_slot(record: dict[str, Any]) -> str:
    """Return the physical target key, independent of device slot numbering.
    返回物理采集目标，不依赖设备菜单序号。

    Args:
        record: Validated capture.（已校验采集。）

    Returns:
        Bare-reference or material/background/thickness key.（裸底或材料/底色/厚度键。）
    """
    if record["sample_role"] == "bare_backing":
        return f"bare:{record['backing']}"
    return f"{record['material_symbol']}:{record['backing']}:{record['overlay_mm']:.2f}"


def normalize_gradient_capture(payload: object) -> dict[str, Any]:
    """Validate raw reflection and its frozen backed-card target.
    校验原始反射及固定的垫底样卡采集目标。

    Args:
        payload: Device or manual capture request.（设备或手动采集请求。）

    Returns:
        Normalized target and unchanged device frame.（规范目标及原样设备帧。）
    """
    allowed = {"capture_id", "material_symbol", "backing", "sample_role", "overlay_mm",
               "measurement", "reflectance_percent_xyz", "measurement_id", "received_at",
               "sample_name", "notes"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise CoreValidationError("The backed-gradient capture contains unsupported fields.")
    symbol, backing, role = (payload.get(key) for key in ("material_symbol", "backing", "sample_role"))
    if symbol not in CAPTURE_MATERIAL_SYMBOLS or backing not in ("W", "K") or role not in ("coated", "bare_backing"):
        raise CoreValidationError("Choose an actual material, black/white backing, and sample role.")
    thickness = _number(payload.get("overlay_mm"), "overlay_mm")
    if role == "bare_backing":
        if thickness != 0 or symbol != backing:
            raise CoreValidationError("A bare reference must use its backing material and zero overlay.")
    elif not any(math.isclose(thickness, point, abs_tol=1e-6, rel_tol=0) for point in THICKNESSES_MM):
        raise CoreValidationError("Overlay thickness must match the seven backed-gradient selections.")
    thickness = round(thickness, 2)
    frame = payload.get("measurement")
    if frame is not None:
        if payload.get("reflectance_percent_xyz") is not None or payload.get("measurement_id") is not None:
            raise CoreValidationError("Supply either an original device frame or a manual reading.")
        if (not isinstance(frame, dict) or frame.get("protocol") != "lumina-box"
                or type(frame.get("version")) is not int or frame["version"] not in (1, 2)
                or frame.get("type") != "measurement" or frame.get("mode") not in ("reflect", "auto")):
            raise CoreValidationError("Use a Lumina Box reflection or AUTO measurement.")
        measurement_id = _text(frame.get("measurement_id"), "measurement_id", 128, required=True)
        device_thickness = _number(frame.get("thickness_mm"), "device thickness_mm")
        if device_thickness <= 0 or (role == "coated" and not math.isclose(device_thickness, thickness, abs_tol=1e-6, rel_tol=0)):
            raise CoreValidationError("The device thickness must match the coated sample's overlay thickness.")
        percent = _xyz(frame.get("reflectance_xyz"))
        if frame["version"] == 1 and max(percent) > 100:
            raise CoreValidationError("Version 1 reflection cannot exceed 100 percent.")
        if frame.get("mode") == "auto" or "transmittance_xyz" in frame:
            if max(_xyz(frame.get("transmittance_xyz"))) > 100:
                raise CoreValidationError("Transmission must remain between 0 and 100 percent.")
        if len(_json(frame).encode("utf-8")) > 4096:
            raise CoreValidationError("The device frame must not exceed 4096 UTF-8 bytes.")
    else:
        percent = _xyz(payload.get("reflectance_percent_xyz"))
        measurement_id = _text(payload.get("measurement_id"), "measurement_id", 128, required=True)
    return {
        "capture_id": _text(payload.get("capture_id"), "capture_id", 64, required=True),
        "measurement_id": measurement_id, "material_symbol": symbol, "backing": backing,
        "sample_role": role, "overlay_mm": thickness, "backing_mm": round(3 - thickness, 2),
        "total_mm": 3.0, "reflectance_percent_xyz": percent,
        "device_measurement": deepcopy(frame), "source": "device" if frame is not None else "manual",
        "received_at": _received_at(payload.get("received_at")),
        "sample_name": _text(payload.get("sample_name", ""), "sample_name", 200),
        "notes": _text(payload.get("notes", ""), "notes", 4000),
    }


def _dataset_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) - {"name", "brand", "material_type", "batch", "notes", "materials"}:
        raise CoreValidationError("The experiment contains unsupported fields.")
    materials = payload.get("materials", {})
    if not isinstance(materials, dict) or set(materials) - set(CAPTURE_MATERIAL_SYMBOLS):
        raise CoreValidationError("Materials must use a supported capture identity.")
    if SINGLE_MATERIAL_SYMBOL in materials and len(materials) != 1:
        raise CoreValidationError("An independent material capture must contain only its own material.")
    keys = (SINGLE_MATERIAL_SYMBOL,) if SINGLE_MATERIAL_SYMBOL in materials else MATERIAL_SYMBOLS
    return {
        "name": _text(payload.get("name"), "name", 200, required=True),
        "brand": _text(payload.get("brand", ""), "brand"),
        "material_type": _text(payload.get("material_type", "PETG"), "material_type", 100),
        "batch": _text(payload.get("batch", ""), "batch"),
        "notes": _text(payload.get("notes", ""), "notes", 4000),
        "materials": {key: _text(materials.get(key, key), "material name", 200, required=True)
                      for key in keys},
    }


class BackedGradientStore:
    """Keep independent experiments and replay receipts in SQLite.
    在SQLite保存独立实验及重放回执。

    Args:
        materials_dir: Library root; existing archives remain untouched.（材料库根目录，现有档案保持原样。）
    """

    def __init__(self, materials_dir: str | Path) -> None:
        self.root = Path(materials_dir)
        self.database = self.root / DATABASE_NAME
        self.results_root = self.root / ".lumina-box-backed-gradient-results"
        if os.name == "nt":
            absolute = str(self.results_root.resolve())
            if not absolute.startswith("\\\\?\\"):
                prefix = "\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\") else "\\\\?\\" + absolute
                self.results_root = Path(prefix)

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if not self.database.resolve().is_relative_to(self.root.resolve()):
                raise CoreValidationError("Experiment storage must remain inside the material library.")
            connection = sqlite3.connect(self.database, timeout=10)
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS gradient_datasets (dataset_id TEXT PRIMARY KEY, document TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS gradient_captures (record_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, "
                "capture_id TEXT NOT NULL, measurement_id TEXT NOT NULL, digest TEXT NOT NULL, "
                "document TEXT NOT NULL, deleted_at TEXT, UNIQUE(capture_id, measurement_id));"
                "CREATE TABLE IF NOT EXISTS gradient_selections (dataset_id TEXT NOT NULL, slot TEXT NOT NULL, "
                "record_id TEXT NOT NULL, PRIMARY KEY(dataset_id, slot));"
                "CREATE TABLE IF NOT EXISTS gradient_fit_runs (fit_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, document TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS gradient_references (reference_id TEXT PRIMARY KEY, document TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS gradient_backing_materials (material_id TEXT PRIMARY KEY, document TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS gradient_backing_material_versions (version_id TEXT PRIMARY KEY, material_id TEXT NOT NULL, document TEXT NOT NULL);"
            )
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            if write:
                connection.commit()
        except (sqlite3.Error, OSError, json.JSONDecodeError) as exc:
            if connection is not None:
                connection.rollback()
            raise CoreProcessingError("Could not access backed-gradient storage. Check local storage and retry.") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _read_dataset(connection: sqlite3.Connection, dataset_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT document FROM gradient_datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
        if row is None:
            raise BackedGradientNotFoundError()
        dataset = json.loads(row[0])
        selected = dict(connection.execute("SELECT slot, record_id FROM gradient_selections WHERE dataset_id=?", (dataset_id,)))
        rows = connection.execute("SELECT document FROM gradient_captures WHERE dataset_id=? AND deleted_at IS NULL ORDER BY rowid", (dataset_id,)).fetchall()
        captures = [json.loads(row[0]) for row in rows]
        for record in captures:
            record["selected"] = selected.get(capture_slot(record)) == record["record_id"]
        return {**dataset, "captures": captures, "selected_capture_ids": selected}

    @staticmethod
    def _bump(connection: sqlite3.Connection, dataset_id: str) -> None:
        row = connection.execute("SELECT document FROM gradient_datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
        if row is None:
            raise BackedGradientNotFoundError()
        document = json.loads(row[0])
        document.update(revision=document["revision"] + 1, updated_at=_now())
        connection.execute("UPDATE gradient_datasets SET document=? WHERE dataset_id=?", (_json(document), dataset_id))

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create one immutable-identity experiment. / 新建一个身份固定的实验。

        Args:
            payload: Name, material identities and batch.（名称、材料身份及批次。）

        Returns:
            Empty durable experiment.（空的持久实验。）
        """
        return self._create(payload)

    def _create(self, payload: dict[str, Any], *, workflow: dict | None = None) -> dict[str, Any]:
        normalized = _dataset_payload(payload)
        stamp = _now()
        dataset = {"schema_version": "1.0", "kind": DATASET_KIND, "dataset_id": str(uuid4()),
                   **normalized, "created_at": stamp, "updated_at": stamp, "revision": 0,
                   "total_mm": 3.0, "observation_face": "bed_contact",
                   "thicknesses_mm": list(THICKNESSES_MM),
                   "calibration_context": {"white_reference_mm": 3.0, "black_reference_mm": 3.0,
                                           "diffuser_removed": True, "black_reference_material": "K"}}
        if workflow is not None:
            dataset["workflow"] = deepcopy(workflow)
        with self._connection(write=True) as connection:
            connection.execute("INSERT INTO gradient_datasets VALUES (?,?)", (dataset["dataset_id"], _json(dataset)))
            return self._read_dataset(connection, dataset["dataset_id"])

    def get(self, dataset_id: str) -> dict[str, Any]:
        """Read an experiment with history and selection. / 读取实验历史及选中读数。

        Args:
            dataset_id: Experiment UUID.（实验UUID。）

        Returns:
            Complete experiment.（完整实验。）
        """
        with self._connection() as connection:
            return self._read_dataset(connection, _uuid(dataset_id))

    def list(self) -> list[dict[str, Any]]:
        """Read saved experiments, newest first. / 按新到旧读取已存实验。

        Returns:
            Experiments including their durable readings.（包含持久读数的实验。）
        """
        with self._connection() as connection:
            ids = connection.execute("SELECT dataset_id FROM gradient_datasets ORDER BY rowid DESC").fetchall()
            return [self._read_dataset(connection, row[0]) for row in ids]

    def save_capture(self, dataset_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        """Append a reading, retaining history and durable idempotence.
        追加读数，保留历史及持久幂等性。

        Args:
            dataset_id: Experiment UUID.（实验UUID。）
            payload: Frozen target and raw measurement.（固定目标及原始测量。）

        Returns:
            Capture, duplicate flag and updated experiment.（采集、重复标志及更新的实验。）
        """
        identity = _uuid(dataset_id)
        normalized = normalize_gradient_capture(payload)
        digest = _digest({"dataset_id": identity, **normalized})
        with self._connection(write=True) as connection:
            dataset = self._read_dataset(connection, identity)
            workflow = dataset.get("workflow", {})
            if workflow.get("kind") == "backing_material":
                role = workflow["material_symbol"]
                expected_backing = role if normalized["sample_role"] == "bare_backing" else ("K" if role == "W" else "W")
                if normalized["material_symbol"] != role or normalized["backing"] != expected_backing:
                    raise BackedGradientConflictError("This reading belongs to a different backing material or sample face.")
            if workflow.get("kind") == "material" and (
                normalized["material_symbol"] != workflow["material_symbol"]
                or normalized["sample_role"] != "coated"
            ):
                raise BackedGradientConflictError("This reading belongs to a different material capture.")
            prior = connection.execute("SELECT document, digest, deleted_at FROM gradient_captures WHERE capture_id=? AND measurement_id=?",
                                       (normalized["capture_id"], normalized["measurement_id"])).fetchone()
            if prior is not None:
                if prior[2] is not None:
                    raise BackedGradientConflictError("This measurement was deleted. Capture a new reading.")
                if prior[1] != digest:
                    raise BackedGradientConflictError("This measurement ID belongs to different data or a different target.")
                record = json.loads(prior[0])
                record["selected"] = dataset["selected_capture_ids"].get(capture_slot(record)) == record["record_id"]
                return record, True, dataset
            stamp = _now()
            record = {"record_id": str(uuid4()), "dataset_id": identity, "created_at": stamp,
                      **normalized, "received_at": normalized["received_at"] or stamp,
                      "capture_context": {key: deepcopy(dataset[key]) for key in
                                          ("brand", "material_type", "batch", "materials", "calibration_context", "observation_face")}}
            record["capture_context"].update(dataset_revision=dataset["revision"], original_received_at=normalized["received_at"])
            connection.execute("INSERT INTO gradient_captures VALUES (?,?,?,?,?,?,NULL)",
                               (record["record_id"], identity, record["capture_id"], record["measurement_id"], digest, _json(record)))
            connection.execute("INSERT OR REPLACE INTO gradient_selections VALUES (?,?,?)", (identity, capture_slot(record), record["record_id"]))
            self._bump(connection, identity)
            return {**record, "selected": True}, False, self._read_dataset(connection, identity)

    def select(self, dataset_id: str, record_id: str) -> dict[str, Any]:
        """Choose an existing reading without altering it. / 选择历史读数，不修改原值。

        Args:
            dataset_id: Experiment UUID.（实验UUID。）
            record_id: Undeleted reading UUID.（未删除读数UUID。）

        Returns:
            Experiment with the updated selection.（已更新选中项的实验。）
        """
        identity, record_identity = _uuid(dataset_id), _uuid(record_id)
        with self._connection(write=True) as connection:
            self._read_dataset(connection, identity)
            row = connection.execute("SELECT document FROM gradient_captures WHERE record_id=? AND dataset_id=? AND deleted_at IS NULL", (record_identity, identity)).fetchone()
            if row is None:
                raise BackedGradientNotFoundError()
            slot = capture_slot(json.loads(row[0]))
            connection.execute("INSERT OR REPLACE INTO gradient_selections VALUES (?,?,?)", (identity, slot, record_identity))
            self._bump(connection, identity)
            return self._read_dataset(connection, identity)

    def delete_capture(self, dataset_id: str, record_id: str) -> dict[str, Any]:
        """Delete one reading while retaining its replay tombstone.
        删除一个读数，保留阻止重放的墓碑。

        Args:
            dataset_id: Experiment UUID.（实验UUID。）
            record_id: Reading UUID.（读数UUID。）

        Returns:
            Updated experiment, with a previous reading selected if available.（更新实验，存在时选回此前读数。）
        """
        identity, record_identity = _uuid(dataset_id), _uuid(record_id)
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT document FROM gradient_captures WHERE record_id=? AND dataset_id=? AND deleted_at IS NULL", (record_identity, identity)).fetchone()
            if row is None:
                raise BackedGradientNotFoundError()
            slot = capture_slot(json.loads(row[0]))
            connection.execute("UPDATE gradient_captures SET deleted_at=? WHERE record_id=?", (_now(), record_identity))
            selected = connection.execute("SELECT record_id FROM gradient_selections WHERE dataset_id=? AND slot=?", (identity, slot)).fetchone()
            if selected and selected[0] == record_identity:
                connection.execute("DELETE FROM gradient_selections WHERE dataset_id=? AND slot=?", (identity, slot))
                candidates = connection.execute("SELECT document FROM gradient_captures WHERE dataset_id=? AND deleted_at IS NULL ORDER BY rowid DESC", (identity,)).fetchall()
                previous = next((json.loads(row[0]) for row in candidates if capture_slot(json.loads(row[0])) == slot), None)
                if previous:
                    connection.execute("INSERT INTO gradient_selections VALUES (?,?,?)", (identity, slot, previous["record_id"]))
            self._bump(connection, identity)
            return self._read_dataset(connection, identity)

    def snapshot(self, dataset_id: str) -> dict[str, Any]:
        """Freeze selected readings and independent bare anchors for fitting.
        冻结用于拟合的选中读数及独立裸底锚。

        Args:
            dataset_id: Experiment UUID.（实验UUID。）

        Returns:
            Reproducible, hashed model input.（可复现并带哈希的模型输入。）
        """
        dataset = self.get(dataset_id)
        selected = [record for record in dataset["captures"] if record["selected"]]
        anchors = {record["backing"]: record["reflectance_percent_xyz"] for record in selected if record["sample_role"] == "bare_backing"}
        missing = [f"bare:{backing}" for backing in ("W", "K") if backing not in anchors]
        if missing:
            raise CoreValidationError("Missing reference readings: " + ", ".join(missing))
        if any(w <= k + 1e-8 for w, k in zip(anchors["W"], anchors["K"])):
            raise CoreValidationError("Bare white must exceed bare black in every XYZ channel.")
        snapshot = {
            "dataset_id": dataset["dataset_id"], "dataset_revision": dataset["revision"],
            "materials": deepcopy(dataset["materials"]), "reference_anchors": deepcopy(anchors),
            "conditions": {"total_mm": 3.0, "observation_face": "bed_contact", "diffuser_removed": True},
            "samples": [{key: deepcopy(record[key]) for key in ("record_id", "material_symbol", "backing", "overlay_mm", "reflectance_percent_xyz", "sample_role")}
                        for record in selected if record["sample_role"] == "coated"],
            "selected_record_ids": sorted(record["record_id"] for record in selected),
        }
        snapshot["input_hash"] = _digest(snapshot)
        return snapshot

    def export(self, dataset_id: str) -> dict[str, Any]:
        """Export readings, selections and deleted receipts. / 导出读数、选择及已删除回执。

        Args:
            dataset_id: Experiment UUID.（实验UUID。）

        Returns:
            Lossless portable experiment document.（无损可携实验文档。）
        """
        identity = _uuid(dataset_id)
        with self._connection() as connection:
            dataset = self._read_dataset(connection, identity)
            deleted = connection.execute("SELECT document, digest, deleted_at FROM gradient_captures WHERE dataset_id=? AND deleted_at IS NOT NULL", (identity,)).fetchall()
            return {"kind": "lumina_box_backed_gradient_export", "schema_version": "1.0", "dataset": dataset,
                    "deleted_receipts": [{"record": json.loads(row[0]), "digest": row[1], "deleted_at": row[2]} for row in deleted]}

    def import_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Merge a portable experiment transactionally, without relabeling data.
        以事务合并可携实验，不改变读数归属。

        Args:
            payload: A backed-gradient export document.（黑白底梯度导出文档。）

        Returns:
            The merged experiment.（已合并实验。）
        """
        from core.backed_gradient_transfer import import_gradient_document

        return import_gradient_document(self, payload)

    def save_run(self, run: dict[str, Any]) -> None:
        """Persist a server-owned fit task state. / 持久化服务器持有的拟合任务状态。

        Args:
            run: Validated server task document.（已校验服务器任务文档。）
        """
        fit_id, dataset_id = _uuid(run["fit_id"]), _uuid(run["dataset_id"])
        with self._connection(write=True) as connection:
            self._read_dataset(connection, dataset_id)
            existing = connection.execute("SELECT document FROM gradient_fit_runs WHERE fit_id=?", (fit_id,)).fetchone()
            if existing is not None:
                previous = json.loads(existing[0])
                if previous["status"] in ("complete", "failed"):
                    return
            connection.execute("INSERT OR REPLACE INTO gradient_fit_runs VALUES (?,?,?)", (fit_id, dataset_id, _json(run)))

    def get_run(self, fit_id: str) -> dict[str, Any]:
        """Read one fit state after navigation or restart. / 切页或重启后读取拟合状态。

        Args:
            fit_id: Fit UUID.（拟合UUID。）

        Returns:
            Persisted task state.（持久任务状态。）
        """
        with self._connection() as connection:
            row = connection.execute("SELECT document FROM gradient_fit_runs WHERE fit_id=?", (_uuid(fit_id),)).fetchone()
            if row is None:
                raise BackedGradientNotFoundError()
            return json.loads(row[0])

    def list_runs(self, dataset_id: str) -> list[dict[str, Any]]:
        """Read fit history for one experiment. / 读取一个实验的拟合历史。

        Args:
            dataset_id: Experiment UUID.（实验UUID。）

        Returns:
            Task history, newest first.（新到旧的任务历史。）
        """
        identity = _uuid(dataset_id)
        with self._connection() as connection:
            self._read_dataset(connection, identity)
            rows = connection.execute("SELECT document FROM gradient_fit_runs WHERE dataset_id=? ORDER BY rowid DESC", (identity,)).fetchall()
            return [json.loads(row[0]) for row in rows]
