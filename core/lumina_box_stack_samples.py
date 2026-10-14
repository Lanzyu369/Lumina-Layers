"""Durable actual stack reflectance samples, independent of material fitting.
独立于耗材拟合的真实叠色反射样片持久化。
"""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import sqlite3
from typing import Any
from uuid import UUID, uuid4

import numpy as np

from core.errors import CoreError, CoreProcessingError, CoreValidationError
from core.km_xyz import km_relative_xyz_to_srgb_uint8
from core.single_stage.materials import resolve_saved_material_dir


STACK_SAMPLE_DATABASE = ".lumina-box-stack-samples.sqlite3"
_RECIPE_SYMBOLS = frozenset("WRYBCMGK")
_PAYLOAD_FIELDS = frozenset({
    "recipe_top_to_bottom", "sample_name", "notes", "capture_id", "measurement",
    "material_batch", "reference_directory_name", "measurement_backing_percent_xyz",
    "received_at",
})


class StackSampleNotFoundError(CoreError):
    """Identify an absent or deleted sample. / 表示样片不存在或已删除。"""

    def __init__(self) -> None:
        super().__init__("The stack sample was not found.", "stack_sample_not_found")


class StackSampleConflictError(CoreError):
    """Reject replay after deletion or identity reuse. / 拒绝删除重放或标识复用。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, "stack_sample_conflict")


def _text(value: object, field: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise CoreValidationError(f"{field} must be text of at most {maximum} characters.")
    if required and not value.strip():
        raise CoreValidationError(f"{field} must not be empty.")
    return value


def _finite_number(value: object, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreValidationError(f"{field} must contain finite numbers.")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise CoreValidationError(f"{field} must contain finite numbers.") from exc
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise CoreValidationError(f"{field} must contain finite {'positive' if positive else 'nonnegative'} numbers.")
    return number


def _xyz(value: object, field: str, *, transmission: bool = False) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CoreValidationError(f"{field} requires exactly three XYZ values.")
    result = [_finite_number(component, field) for component in value]
    if transmission and any(component > 100 for component in result):
        raise CoreValidationError(f"{field} must be between 0 and 100 percent.")
    return result


def _received_at(value: object) -> str | None:
    if value is None:
        return None
    timestamp = _text(value, "received_at", 128, required=True)
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise CoreValidationError("received_at must be a timezone-aware ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CoreValidationError("received_at must include its timezone.")
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_stack_recipe(recipe: object) -> str:
    """Normalize an outside-to-inside recipe while retaining its layer order.
    规范化外观面到内部的配方并保留其层序。

    Args:
        recipe: One to 35 material symbols, with optional whitespace.（一至35个材料字母，可含空白。）

    Returns:
        Uppercase material symbols in the original order.（原顺序的大写材料字母。）
    """
    value = _text(recipe, "recipe_top_to_bottom", 256, required=True)
    normalized = "".join(value.split()).upper()
    if not 1 <= len(normalized) <= 35 or set(normalized) - _RECIPE_SYMBOLS:
        raise CoreValidationError("Use 1 to 35 layer symbols from W R Y B C M G K, outside to inside.")
    return normalized


def normalize_stack_sample_payload(payload: object) -> dict[str, Any]:
    """Validate raw capture input without fitting or correcting measurements.
    校验原始采集输入，不拟合或修正测量值。

    Args:
        payload: Sample recipe, provenance, and original firmware measurement.（样片配方、来源与固件原始测量。）

    Returns:
        Validated input with a normalized recipe and explicit defaults.（配方已规范化且默认值明确的输入。）
    """
    if not isinstance(payload, dict) or set(payload) - _PAYLOAD_FIELDS:
        raise CoreValidationError("Stack sample input contains unsupported fields.")
    measurement = payload.get("measurement")
    if not isinstance(measurement, dict):
        raise CoreValidationError("A Lumina Box reflection measurement is required.")
    if (
        measurement.get("protocol") != "lumina-box"
        or type(measurement.get("version")) is not int
        or measurement["version"] not in (1, 2)
        or measurement.get("type") != "measurement"
        or measurement.get("mode") not in ("auto", "reflect")
    ):
        raise CoreValidationError("Use a Lumina Box v1/v2 AUTO or reflection measurement.")
    _text(measurement.get("measurement_id"), "measurement_id", 128, required=True)
    _finite_number(measurement.get("thickness_mm"), "device thickness_mm", positive=True)
    reflectance = _xyz(measurement.get("reflectance_xyz"), "reflectance_xyz")
    if measurement["version"] == 1 and any(value > 100 for value in reflectance):
        raise CoreValidationError("Lumina Box v1 reflectance_xyz must be between 0 and 100 percent.")
    if measurement["mode"] == "auto" and "transmittance_xyz" not in measurement:
        raise CoreValidationError("An AUTO measurement requires both reflection and transmission XYZ.")
    if "transmittance_xyz" in measurement:
        _xyz(measurement["transmittance_xyz"], "transmittance_xyz", transmission=True)
    try:
        frame_bytes = json.dumps(
            measurement, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise CoreValidationError("The original measurement must contain finite UTF-8 JSON data.") from exc
    if len(frame_bytes) > 4096:
        raise CoreValidationError("The original measurement JSON must not exceed 4096 UTF-8 bytes.")
    reference = payload.get("reference_directory_name")
    if reference is not None:
        reference = _text(reference, "reference_directory_name", 512).strip().replace("\\", "/")
        parts = PurePosixPath(reference).parts
        if reference and (reference.startswith("/") or ":" in reference or ".." in parts):
            raise CoreValidationError("reference_directory_name must remain inside the material library.")
        reference = reference or None
    backing = payload.get("measurement_backing_percent_xyz")
    normalized = {
        "recipe_top_to_bottom": normalize_stack_recipe(payload.get("recipe_top_to_bottom")),
        "capture_id": _text(payload.get("capture_id"), "capture_id", 64, required=True),
        "measurement": deepcopy(measurement),
        "received_at": _received_at(payload.get("received_at")),
        "sample_name": _text(payload.get("sample_name", ""), "sample_name", 200),
        "notes": _text(payload.get("notes", ""), "notes", 4000),
        "material_batch": _text(payload.get("material_batch", ""), "material_batch", 500),
        "reference_directory_name": reference,
        "measurement_backing_percent_xyz": (
            None if backing is None else _xyz(backing, "measurement_backing_percent_xyz")
        ),
    }
    try:
        json.dumps(normalized, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise CoreValidationError("Stack sample input must contain finite UTF-8 JSON data.") from exc
    return normalized


def _geometry(recipe: str) -> dict[str, Any]:
    count = len(recipe)
    return {
        "upper_layer_count": count,
        "upper_layer_height_mm": 0.08,
        "first_layer_height_mm": 0.20,
        "total_layer_count": 36,
        "upper_mm": count * 8 / 100,
        "white_base_mm": (300 - count * 8) / 100,
        "total_mm": 3.0,
        "full_recipe_top_to_bottom": recipe + "W" * (36 - count),
        "layer_heights_mm_top_to_bottom": [0.08] * 35 + [0.20],
    }


def _reference_context(root: Path, directory: str | None) -> dict[str, Any]:
    context: dict[str, Any] = {
        "status": "not_selected" if directory is None else "unavailable",
        "archive_id": None, "revision_id": None, "reference_id": None,
        "sidecar_sha256": {},
    }
    if directory is None:
        return context
    try:
        reference = resolve_saved_material_dir(root, directory)
        for filename in (
            "material.json", "lumina_box_measurements.json", "lumina_box_spectral_parameters.json",
        ):
            path = reference / filename
            if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                continue
            data = path.read_bytes()
            context["sidecar_sha256"][filename] = hashlib.sha256(data).hexdigest()
            document = json.loads(data.decode("utf-8"))
            consistency = document.get("archive_consistency", {})
            for key in ("archive_id", "revision_id", "reference_id"):
                value = consistency.get(key) or document.get(key)
                if isinstance(value, str):
                    context[key] = value
        if context["sidecar_sha256"]:
            context["status"] = "captured"
    except (OSError, ValueError, TypeError, AttributeError):
        # Optional provenance must not gate collecting actual measurements.
        context["status"] = "unavailable"
    return context


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    measurement = payload["measurement"]
    percent = _xyz(measurement["reflectance_xyz"], "reflectance_xyz")
    relative = [value / 100.0 for value in percent]
    rgb = km_relative_xyz_to_srgb_uint8(np.array(relative)).tolist()
    created_at = _timestamp()
    return {
        "schema_version": "1.0", "kind": "lumina_box_stack_sample",
        "data_role": "actual_measured_multimaterial_reflectance",
        "record_id": str(uuid4()), "created_at": created_at,
        **{key: value for key, value in payload.items() if key != "measurement"},
        "received_at": payload["received_at"] or created_at,
        "geometry": _geometry(payload["recipe_top_to_bottom"]),
        "reflectance_percent_xyz": percent,
        "reflectance_relative_xyz": relative,
        "display_rgb": rgb,
        "display_hex": "#" + "".join(f"{value:02X}" for value in rgb),
        "device_measurement": measurement,
        "reference_context": _reference_context(root, payload["reference_directory_name"]),
    }


class StackSampleStore:
    """Store actual samples with transactional replay protection.
    以事务保存真实样片，并阻止重复消息重建已删除数据。

    Args:
        materials_dir: Existing material-library location used only for a separate database.（材料库位置，仅新增独立数据库。）
    """

    def __init__(self, materials_dir: str | Path) -> None:
        self.root = Path(materials_dir)
        self.database = self.root / STACK_SAMPLE_DATABASE

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.database.resolve().is_relative_to(self.root.resolve()):
            raise CoreValidationError("The stack-sample database must remain inside the material library.")
        connection = sqlite3.connect(str(self.database), timeout=5.0)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS stack_samples ("
                "record_id TEXT PRIMARY KEY, capture_id TEXT NOT NULL, "
                "measurement_id TEXT NOT NULL, payload_digest TEXT NOT NULL, "
                "created_at TEXT NOT NULL, record_json TEXT, deleted_at TEXT, "
                "UNIQUE(capture_id, measurement_id))"
            )
            connection.commit()
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    def save(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Commit one capture, returning the saved sample and replay status.
        提交一次采集，返回样片与是否为重复投递。

        Args:
            payload: Raw recipe and device capture input.（原始配方及设备采集输入。）

        Returns:
            Saved record and whether an identical capture already existed.（已存记录及相同采集是否已存在。）
        """
        normalized = normalize_stack_sample_payload(payload)
        digest = hashlib.sha256(json.dumps(
            normalized, sort_keys=True, ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")).hexdigest()
        measurement_id = normalized["measurement"]["measurement_id"]
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT record_json, deleted_at, payload_digest FROM stack_samples "
                    "WHERE capture_id = ? AND measurement_id = ?",
                    (normalized["capture_id"], measurement_id),
                ).fetchone()
                if existing is not None:
                    if existing[1] is not None:
                        raise StackSampleConflictError(
                            "This capture was deleted. Take a new measurement to save another sample."
                        )
                    if existing[2] != digest:
                        raise StackSampleConflictError(
                            "This capture ID already belongs to different sample data. "
                            "Retry the original capture or take a new measurement."
                        )
                    return json.loads(existing[0]), True
                record = _record(normalized, self.root)
                connection.execute(
                    "INSERT INTO stack_samples "
                    "(record_id, capture_id, measurement_id, payload_digest, created_at, record_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (record["record_id"], normalized["capture_id"], measurement_id, digest,
                     record["created_at"], json.dumps(record, ensure_ascii=False, allow_nan=False)),
                )
                return record, False
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise CoreProcessingError(
                "Could not save the stack sample. Check local database storage and retry."
            ) from exc

    def list(self) -> list[dict[str, Any]]:
        """Read all undeleted captures, newest first. / 按时间倒序读取未删除采集。

        Returns:
            Complete capture records in descending time order.（按时间倒序排列的完整采集记录。）
        """
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT record_json FROM stack_samples WHERE deleted_at IS NULL "
                    "ORDER BY created_at DESC, record_id DESC"
                ).fetchall()
            return [json.loads(row[0]) for row in rows]
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise CoreProcessingError("Could not read stack samples. Check local database storage.") from exc

    def get(self, record_id: str) -> dict[str, Any]:
        """Read one sample by UUID. / 按UUID读取一条样片。

        Args:
            record_id: Durable sample UUID.（持久样片UUID。）

        Returns:
            The complete undeleted capture.（未删除的完整采集记录。）
        """
        identity = self._uuid(record_id)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT record_json FROM stack_samples WHERE record_id = ? AND deleted_at IS NULL",
                    (identity,),
                ).fetchone()
            if row is None:
                raise StackSampleNotFoundError()
            return json.loads(row[0])
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise CoreProcessingError("Could not read the stack sample. Check local database storage.") from exc

    def delete(self, record_id: str) -> None:
        """Delete only this capture and retain its replay tombstone.
        仅删除当前采集，保留阻止消息重放的标记。

        Args:
            record_id: UUID of the single selected sample.（唯一选中样片的UUID。）
        """
        identity = self._uuid(record_id)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE stack_samples SET record_json = NULL, deleted_at = ? "
                    "WHERE record_id = ? AND deleted_at IS NULL",
                    (_timestamp(), identity),
                )
                if cursor.rowcount == 0:
                    raise StackSampleNotFoundError()
        except (sqlite3.Error, OSError) as exc:
            raise CoreProcessingError(
                "Could not delete the stack sample. Check local database storage and retry."
            ) from exc

    @staticmethod
    def _uuid(record_id: str) -> str:
        try:
            return str(UUID(record_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise CoreValidationError("record_id must be a UUID.") from exc
