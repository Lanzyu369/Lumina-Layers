"""Shared backed-gradient snapshot validation and bounded prediction helpers.
黑白底梯度的共享快照校验与有时限预测辅助函数。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import time
from typing import Sequence

import numpy as np

from core.backed_gradient_optics import BackedGradientOptics, MATERIAL_SYMBOLS
from core.backed_gradient_store import THICKNESSES_MM
from core.errors import CoreValidationError

VALIDATION_THICKNESS_MM = .24


class BackedGradientFitTimeout(TimeoutError):
    """The calibration fit exhausted its caller-visible time allowance.
    标定拟合耗尽调用方可见的时间额度。
    """


@dataclass
class _Prepared:
    anchors: dict
    total: float
    training: list[dict]
    validation: list[dict]
    controls: list[dict]
    present: tuple[str, ...]


def _prepare(snapshot: dict, include_validation: bool) -> _Prepared:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("samples"), list):
        raise CoreValidationError("A backed-gradient snapshot must contain a sample list")
    if not isinstance(snapshot.get("conditions"), dict) or not isinstance(snapshot.get("reference_anchors"), dict):
        raise CoreValidationError("Snapshot conditions and bare anchors must be objects")
    if (snapshot["conditions"].get("observation_face") != "bed_contact"
            or snapshot["conditions"].get("diffuser_removed") is not True):
        raise CoreValidationError("This workflow requires the bed-contact face and removed diffuser")
    try:
        for values in snapshot["reference_anchors"].values():
            if not isinstance(values, (list, tuple)) or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
                raise CoreValidationError("Bare anchors must contain actual numeric XYZ values")
        anchors = {key: np.asarray(snapshot["reference_anchors"][key], float).tolist() for key in ("W", "K")}
        if isinstance(snapshot["conditions"]["total_mm"], bool):
            raise CoreValidationError("Total thickness must be numeric, not boolean")
        total = float(snapshot["conditions"]["total_mm"])
    except (KeyError, TypeError, ValueError) as error:
        raise CoreValidationError("The backed-gradient snapshot needs measured bare W/K anchors and thickness") from error
    if not np.isfinite(total) or abs(total - 3.) > 1e-8:
        raise CoreValidationError("This first backed-gradient workflow requires a complete three-mm sample")
    if (any(np.asarray(anchors[key]).shape != (3,) or not np.isfinite(anchors[key]).all() for key in ("W", "K"))
            or any(value < 0 for values in anchors.values() for value in values)
            or np.any(np.asarray(anchors["W"]) <= anchors["K"])):
        raise CoreValidationError("Measured bare white anchors must be finite and exceed nonnegative bare black anchors")
    training, validation, controls = [], [], []
    seen = set()
    for source in snapshot.get("samples", []):
        try:
            if (not isinstance(source, dict) or isinstance(source["overlay_mm"], bool)
                    or not isinstance(source["overlay_mm"], (int, float))
                    or not isinstance(source["reflectance_percent_xyz"], (list, tuple))
                    or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in source["reflectance_percent_xyz"])
                    or not isinstance(source.get("record_id"), str) or not source["record_id"].strip()):
                raise CoreValidationError("Samples need numeric thickness/XYZ and a record identity")
            row = {**source, "overlay_mm": float(source["overlay_mm"]),
                   "reflectance_percent_xyz": np.asarray(source["reflectance_percent_xyz"], float).tolist()}
            values = np.asarray(row["reflectance_percent_xyz"])
            symbol, backing = row["material_symbol"], row["backing"]
        except (KeyError, TypeError, ValueError) as error:
            raise CoreValidationError("A backed-gradient sample is incomplete") from error
        if (symbol not in MATERIAL_SYMBOLS or backing not in ("W", "K") or values.shape != (3,)
                or not np.isfinite(values).all() or np.any(values < 0)
                or not np.isfinite(row["overlay_mm"]) or not 0 <= row["overlay_mm"] <= total):
            raise CoreValidationError("Sample XYZ must be nonnegative finite readings with a valid finite backing")
        row["sample_role"] = source.get("sample_role", "coated")
        if row["sample_role"] not in ("coated", "bare_backing"):
            raise CoreValidationError("Unknown backed-gradient sample role")
        if row["sample_role"] == "bare_backing":
            if symbol != backing or row["overlay_mm"] != 0:
                raise CoreValidationError("A bare anchor must have zero overlay and its own backing material")
        else:
            canonical = next((point for point in THICKNESSES_MM if abs(row["overlay_mm"] - point) <= 1e-6), None)
            if canonical is None:
                raise CoreValidationError("The overlay must match one of the seven declared thicknesses")
            row["overlay_mm"] = canonical
        identity = symbol, backing, row["overlay_mm"]
        if identity in seen:
            raise CoreValidationError("Select one active record for each material/backing/thickness")
        seen.add(identity)
        if symbol == backing or row["sample_role"] != "coated" or row["overlay_mm"] == 0:
            controls.append(row)
        elif not include_validation and abs(row["overlay_mm"] - VALIDATION_THICKNESS_MM) < 1e-8:
            # Keep the raw record untouched; no validation XYZ enters optimizer arrays.
            validation.append(row)
        else:
            training.append(row)
    present = tuple(symbol for symbol in MATERIAL_SYMBOLS if any(row["material_symbol"] == symbol for row in training))
    if not {"W", "K"}.issubset(present):
        raise CoreValidationError("Joint white-on-black and black-on-white measurements are required")
    for symbol in present:
        rows = [row for row in training if row["material_symbol"] == symbol]
        if len({row["overlay_mm"] for row in rows}) < 3:
            raise CoreValidationError(f"Material {symbol} needs at least three non-validation thicknesses")
        if symbol not in ("W", "K"):
            grouped = defaultdict(set)
            for row in rows:
                grouped[round(row["overlay_mm"], 6)].add(row["backing"])
            if any(backings != {"W", "K"} for backings in grouped.values()):
                raise CoreValidationError(f"Material {symbol} needs paired W/K backgrounds at each thickness")
    return _Prepared(anchors, total, training, validation, controls, present)


def _predict_rows(operator: BackedGradientOptics, rows: Sequence[dict]) -> np.ndarray:
    output = np.empty((len(rows), 3))
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        groups[row["material_symbol"], row["backing"]].append(index)
    for (material, backing), indices in groups.items():
        thicknesses = np.array([rows[index]["overlay_mm"] for index in indices])
        output[indices] = operator.predict_backed(material, backing, thicknesses)
    return output


def _deadline_check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise BackedGradientFitTimeout("Backed-gradient fitting exceeded its bounded time allowance")
